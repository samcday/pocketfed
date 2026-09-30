/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Compile the production helper against synthetic PAM entry points. No host
 * PAM module, biometric device, secret, or system authentication is accessed. */
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define main worker_main
#include "phosh-fingerprint-worker.c"
#undef main

static int auth_result, account_result, end_result, start_result;
static int auth_calls, account_calls, end_calls;
static int block_auth;
static const struct pam_conv *active_conversation;

int pam_start(const char *service, const char *username,
              const struct pam_conv *conv, pam_handle_t **handle)
{
    assert(strcmp(service, "phosh-fingerprint") == 0);
    assert(strcmp(username, getpwuid(getuid())->pw_name) == 0);
    assert(conv->conv == conversation);
    active_conversation = conv;
    *handle = (pam_handle_t *) 1;
    return start_result;
}
int pam_authenticate(pam_handle_t *handle, int flags)
{
    assert(handle == (pam_handle_t *) 1);
    assert(flags & PAM_DISALLOW_NULL_AUTHTOK);
    auth_calls++;
    if (block_auth) {
        const struct pam_message message = { PAM_TEXT_INFO, "ready" };
        const struct pam_message *ptr = &message;
        struct pam_response *response = NULL;
        assert(active_conversation->conv(1, &ptr, &response,
                                         active_conversation->appdata_ptr) == PAM_SUCCESS);
        free(response);
        for (;;) pause();
    }
    return auth_result;
}
int pam_acct_mgmt(pam_handle_t *handle, int flags)
{
    assert(handle == (pam_handle_t *) 1);
    assert(flags == 0);
    account_calls++;
    return account_result;
}
int pam_end(pam_handle_t *handle, int status)
{
    assert(handle == (pam_handle_t *) 1);
    assert(status == (auth_result ? auth_result : account_result));
    end_calls++;
    return end_result;
}
static void reset(void)
{
    auth_result = account_result = end_result = start_result = PAM_SUCCESS;
    auth_calls = account_calls = end_calls = 0;
    block_auth = 0;
}

static void worker_socket_test(int cancel)
{
    if (getuid() != 0) {
        puts("worker socket integration: root-only case skipped on this host");
        return;
    }
    int sockets[2], status;
    unsigned char type, data[FINGERPRINT_MESSAGE_MAX];
    uint32_t length;
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    reset();
    block_auth = cancel;
    pid_t worker = fork();
    assert(worker >= 0);
    if (!worker) {
        char *args[] = { "worker", NULL };
        close(sockets[0]);
        assert(dup2(sockets[1], STDIN_FILENO) >= 0);
        if (sockets[1] != STDIN_FILENO) close(sockets[1]);
        _exit(worker_main(1, args));
    }
    close(sockets[1]);
    struct pollfd ready = { .fd = sockets[0], .events = POLLIN };
    assert(poll(&ready, 1, 2000) == 1);
    assert(fingerprint_receive(sockets[0], &type, data, &length) == 0);
    if (cancel) {
        assert(type == FINGERPRINT_MESSAGE && length == 5 && !memcmp(data, "ready", 5));
    } else {
        assert(type == FINGERPRINT_RESULT && length == 1 && data[0] == 0);
    }
    if (cancel) close(sockets[0]);
    /* A regression cannot hang package checks indefinitely. */
    alarm(3);
    assert(waitpid(worker, &status, 0) == worker);
    alarm(0);
    if (!cancel) close(sockets[0]);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == (cancel ? 1 : 0));
}
int main(void)
{
    char *args[] = { "phosh-fingerprint-worker", NULL };
    const char *username = getpwuid(getuid())->pw_name;
    struct pam_response *reply = NULL;
    const struct pam_message info = { PAM_TEXT_INFO, NULL };
    const struct pam_message error = { PAM_ERROR_MSG, NULL };
    const struct pam_message secret = { PAM_PROMPT_ECHO_OFF, NULL };
    const struct pam_message echo = { PAM_PROMPT_ECHO_ON, NULL };
    const struct pam_message *messages[] = { &info, &error };
    assert(conversation(2, messages, &reply, NULL) == PAM_SUCCESS);
    assert(reply && !reply[0].resp && !reply[1].resp);
    free(reply);
    messages[1] = &secret;
    assert(conversation(2, messages, &reply, NULL) == PAM_CONV_ERR && !reply);
    messages[1] = &echo;
    assert(conversation(2, messages, &reply, NULL) == PAM_CONV_ERR && !reply);
    messages[1] = NULL;
    assert(conversation(2, messages, &reply, NULL) == PAM_CONV_ERR && !reply);
    assert(conversation(0, messages, &reply, NULL) == PAM_CONV_ERR);
    assert(conversation(1, messages, NULL, NULL) == PAM_CONV_ERR);
    reset();
    assert(authenticate_user(username, -1) == 0);
    assert(auth_calls == 1 && account_calls == 1 && end_calls == 1);
    reset(); auth_result = PAM_AUTH_ERR;
    assert(authenticate_user(username, -1) == 1);
    assert(auth_calls == 1 && account_calls == 0 && end_calls == 1);
    reset(); account_result = PAM_ACCT_EXPIRED;
    assert(authenticate_user(username, -1) == 1 && account_calls == 1 && end_calls == 1);
    reset(); account_result = PAM_CONV_ERR;
    assert(authenticate_user(username, -1) == 1);
    reset(); end_result = PAM_SYSTEM_ERR;
    assert(authenticate_user(username, -1) == 1);
    reset(); start_result = PAM_SYSTEM_ERR;
    assert(authenticate_user(username, -1) == 2 && auth_calls == 0 && end_calls == 0);
    reset();
    assert(worker_main(2, args) == 2 && auth_calls == 0);
    worker_socket_test(0);
    worker_socket_test(1);
    puts("helper: info-only conversation, prompt rejection, auth/account/cleanup failures and fixed-service checks passed");
    return 0;
}
