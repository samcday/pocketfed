/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Fixed-size lab export using OpenSSL's RSA-OAEP implementation. No TEE access. */
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
    unsigned char plain[160] = {0}, cipher[384] = {0};
    size_t length = sizeof cipher;
    EVP_PKEY *key = NULL;
    EVP_PKEY_CTX *context = NULL;
    FILE *file = NULL;
    int result = 1;
    if (argc != 2) goto out;
    file = fopen(argv[1], "r");
    if (!file) goto out;
    key = PEM_read_PUBKEY(file, NULL, NULL, NULL);
    fclose(file); file = NULL;
    if (!key || !EVP_PKEY_is_a(key, "RSA") || EVP_PKEY_get_bits(key) != 3072 ||
        EVP_PKEY_get_size(key) != sizeof cipher) goto out;
    context = EVP_PKEY_CTX_new(key, NULL);
    if (!context || EVP_PKEY_encrypt_init(context) <= 0 ||
        EVP_PKEY_CTX_set_rsa_padding(context, RSA_PKCS1_OAEP_PADDING) <= 0 ||
        EVP_PKEY_CTX_set_rsa_oaep_md(context, EVP_sha256()) <= 0 ||
        EVP_PKEY_CTX_set_rsa_mgf1_md(context, EVP_sha256()) <= 0) goto out;
    if (fread(plain, 1, sizeof plain, stdin) != sizeof plain ||
        fgetc(stdin) != EOF || ferror(stdin)) goto out;
    if (EVP_PKEY_encrypt(context, cipher, &length, plain, sizeof plain) <= 0 ||
        length != sizeof cipher) goto out;
    if (fwrite(cipher, 1, length, stdout) != length || fflush(stdout)) goto out;
    result = 0;
out:
    if (file) fclose(file);
    EVP_PKEY_CTX_free(context);
    EVP_PKEY_free(key);
    OPENSSL_cleanse(plain, sizeof plain);
    OPENSSL_cleanse(cipher, sizeof cipher);
    return result;
}
