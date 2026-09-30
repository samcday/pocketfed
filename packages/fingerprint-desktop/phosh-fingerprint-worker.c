/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Invoked by a root-owned Accept=yes systemd Unix socket service.
 * Homed RefHome requires privilege even after fingerprint authentication.
 * The user comes exclusively from kernel SO_PEERCRED, never from a request.
 */
#define _GNU_SOURCE
#include "fingerprint-wire.h"
#include <poll.h>
#include <pwd.h>
#include <security/pam_appl.h>
#include <signal.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <sys/prctl.h>
#include <sys/wait.h>

static int
conversation(int count, const struct pam_message **messages,
             struct pam_response **responses, void *context)
{
    int fd = context ? *(const int *)context : -1;
    if (count <= 0 || count > PAM_MAX_NUM_MSG || !messages || !responses)
        return PAM_CONV_ERR;
    *responses = NULL;
    for (int i = 0; i < count; i++) {
        if (!messages[i] || (messages[i]->msg_style != PAM_TEXT_INFO &&
                             messages[i]->msg_style != PAM_ERROR_MSG) ||
            (messages[i]->msg && strlen(messages[i]->msg) > FINGERPRINT_MESSAGE_MAX))
            return PAM_CONV_ERR;
    }
    struct pam_response *reply = calloc((size_t)count, sizeof(*reply));
    if (!reply) return PAM_BUF_ERR;
    for (int i = 0; i < count; i++) {
        if (fd >= 0 && messages[i]->msg &&
            fingerprint_send(fd, FINGERPRINT_MESSAGE, messages[i]->msg,
                             (uint32_t)strlen(messages[i]->msg))) {
            free(reply);
            return PAM_CONV_ERR;
        }
    }
    *responses = reply;
    return PAM_SUCCESS;
}

static int
authenticate_user(const char *username, int fd)
{
    pam_handle_t *handle = NULL;
    const struct pam_conv conv = { conversation, &fd };
    int result = pam_start("phosh-fingerprint", username, &conv, &handle);
    if (result != PAM_SUCCESS) return 2;
    result = pam_authenticate(handle, PAM_DISALLOW_NULL_AUTHTOK);
    if (result == PAM_SUCCESS) result = pam_acct_mgmt(handle, 0);
    int cleanup = pam_end(handle, result);
    return result == PAM_SUCCESS && cleanup == PAM_SUCCESS ? 0 : 1;
}

int
main(int argc, char **argv)
{
    struct ucred peer = {0};
    socklen_t size = sizeof(peer);
    struct passwd *user;
    pid_t child, supervisor = getpid();
    int status;
    (void)argv;
    if (argc != 1 || getuid() != 0 || geteuid() != 0 ||
        getsockopt(STDIN_FILENO, SOL_SOCKET, SO_PEERCRED, &peer, &size) ||
        size != sizeof(peer)) return 2;
    user = getpwuid(peer.uid);
    if (!user || !user->pw_name || !user->pw_name[0]) return 2;
    signal(SIGPIPE, SIG_IGN);
    child = fork();
    if (child < 0) return 2;
    if (child == 0) {
        if (prctl(PR_SET_PDEATHSIG, SIGKILL) || getppid() != supervisor) _exit(2);
        unsigned char result = (unsigned char)authenticate_user(user->pw_name, STDIN_FILENO);
        fingerprint_send(STDIN_FILENO, FINGERPRINT_RESULT, &result, 1);
        _exit(result);
    }
    /* PAM may block. Watch disconnect independently, then kill/reap the PAM
     * child to close its fprintd connection. The unit's RuntimeMaxSec bounds a
     * stalled module. No client input is valid. */
    for (;;) {
        pid_t done = waitpid(child, &status, WNOHANG);
        if (done == child) return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
        if (done < 0 && errno != EINTR) return 1;
        struct pollfd connection = { .fd = STDIN_FILENO, .events = POLLIN | POLLRDHUP };
        int result = poll(&connection, 1, 250);
        if ((result < 0 && errno != EINTR) || (result > 0 && connection.revents)) {
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
            return 1;
        }
    }
}
