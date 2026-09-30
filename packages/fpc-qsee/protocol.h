/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef FPC_QSEE_PROTOCOL_H
#define FPC_QSEE_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FPC_QSEE_APP_NAME "fpctzappfingerprint"
#define FPC_KEYMASTER_APP_NAME "keymaster64"
#define FPC_QSEE_ALIGNMENT 64u
#define FPC_QSEE_OUTER_SIZE 64u
#define FPC_QSEE_AUX_POINTER_OFFSET 4u
#define FPC_QSEE_MAX_AUX_SIZE (1024u * 1024u)
#define FPC_SENSOR_COMMAND_SIZE 88u
#define FPC_BIO_COMMAND_SIZE 40u
#define FPC_HAT_SIZE 69u
#define FPC_MAX_TEMPLATES 5u

/* Callback replaces aux with the TA response. Return 0 or negative errno.
 * The callback must return the separate outer dispatcher status at *outer.
 * No buffer may be logged: some commands contain authentication tokens.
 */
typedef int (*fpc_qsee_exchange_fn)(void *ctx, void *aux, size_t len,
                                    int32_t *outer);
struct fpc_protocol {
    void *ctx;
    fpc_qsee_exchange_fn exchange;
};
struct fpc_result {
    int transport;
    int32_t outer;
    int32_t command;
};
enum fpc_target {
    FPC_TARGET_FS = 2,
    FPC_TARGET_AUTH = 3,
    FPC_TARGET_SENSOR = 10,
    FPC_TARGET_BIO = 11,
    FPC_TARGET_COMMON = 12,
};
enum fpc_sensor_command {
    FPC_SENSOR_INIT = 0,
    FPC_SENSOR_CHECK_FINGER_LOST = 1,
    FPC_SENSOR_FINGER_LOST_WAKEUP_SETUP = 2,
    FPC_SENSOR_WAKEUP_SETUP = 3,
    FPC_SENSOR_QUALIFY_CAPTURE = 4,
    FPC_SENSOR_DEEP_SLEEP = 5,
    FPC_SENSOR_OTP_SUPPORTED = 6,
    FPC_SENSOR_OTP_INFO = 7,
};
enum fpc_bio_command {
    FPC_BIO_BEGIN_ENROL = 0,
    FPC_BIO_ENROL = 1,
    FPC_BIO_END_ENROL = 2,
    FPC_BIO_IDENTIFY = 3,
    FPC_BIO_UPDATE_TEMPLATE = 4,
    FPC_BIO_LOAD_EMPTY_DB = 6,
    FPC_BIO_GET_TEMPLATE_IDS = 7,
    FPC_BIO_DELETE_TEMPLATE = 8,
    FPC_BIO_SET_ACTIVE_SET = 9,
    FPC_BIO_GET_DB_ID = 10,
};
enum fpc_auth_command {
    FPC_AUTH_SET_AUTH_CHALLENGE = 1,
    FPC_AUTH_GET_ENROL_CHALLENGE = 2,
    FPC_AUTH_AUTHORIZE_ENROL = 3,
    FPC_AUTH_GET_AUTH_RESULT = 4,
    FPC_AUTH_IMPORT_WRAPPED_KEY = 5,
    FPC_AUTH_CHECK_ENROL_TIMEOUT = 6,
};
struct fpc_identify_result {
    struct fpc_result result;
    uint32_t template_id;
    uint32_t decision;
    /* Algorithm diagnostics: names beyond decision require more validation. */
    uint32_t diagnostic[6];
};

uint32_t fpc_get_le32(const void *src);
uint64_t fpc_get_le64(const void *src);
void fpc_put_le32(void *dst, uint32_t value);
void fpc_put_le64(void *dst, uint64_t value);
bool fpc_result_ok(struct fpc_result result);
bool fpc_identify_matched(const struct fpc_identify_result *result);

/* Constructs the padded packed outer {u32 size,u64 address} request. */
int fpc_outer_encode(void *request, size_t capacity, uint32_t aux_len,
                     uint64_t aux_physical_address);
struct fpc_result fpc_sensor(struct fpc_protocol *p,
                             enum fpc_sensor_command command,
                             uint32_t *capture_detail);
/* parameter is command-specific in/out at offset12; see protocol.md. */
struct fpc_result fpc_bio(struct fpc_protocol *p, enum fpc_bio_command command,
                          uint32_t *parameter);
struct fpc_result fpc_get_template_ids(struct fpc_protocol *p,
                                      uint32_t ids[FPC_MAX_TEMPLATES],
                                      uint32_t *count);
struct fpc_identify_result fpc_identify(struct fpc_protocol *p);
struct fpc_result fpc_get_database_id(struct fpc_protocol *p, uint64_t *id);
struct fpc_result fpc_database_file(struct fpc_protocol *p, bool store,
                                    const char *path);
struct fpc_result fpc_auth_challenge(struct fpc_protocol *p, bool enrollment,
                                    uint64_t *challenge);
struct fpc_result fpc_auth_import_key(struct fpc_protocol *p,
                                      const void *wrapped_key, size_t len);
struct fpc_result fpc_auth_authorize_enrol(struct fpc_protocol *p,
                                          const uint8_t hat[FPC_HAT_SIZE]);
struct fpc_result fpc_auth_get_result(struct fpc_protocol *p,
                                     uint8_t hat[FPC_HAT_SIZE]);
struct fpc_result fpc_auth_enrol_timeout(struct fpc_protocol *p,
                                        uint32_t seconds, bool start);
/* Keymaster command517/version2, request64, response960. No key material
 * is interpreted here. Successful response returns an opaque wrapped blob.
 */
void fpc_keymaster_key_request(uint8_t request[FPC_QSEE_OUTER_SIZE]);
int fpc_keymaster_key_response(const void *response, size_t response_len,
                               const void **wrapped_key, size_t *key_len);
#endif
