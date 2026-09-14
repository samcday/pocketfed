#include <assert.h>
#include <math.h>
#include <stdio.h>
typedef struct { float neutral[3]; } libdng_info;
static struct { float red, blue; } state_proc;
static void libdng_set_neutral(libdng_info *dng, float r, float g, float b) {
    dng->neutral[0]=r; dng->neutral[1]=g; dng->neutral[2]=b;
}
static libdng_info export(void) {
    libdng_info dng={0};
#include "neutral-export.c"
    return dng;
}
static void close_to(float actual, float expected) { assert(fabsf(actual-expected)<0.00001f); }
int main(void) {
    state_proc.red=2; state_proc.blue=1.5f;
    libdng_info dng=export();
    close_to(dng.neutral[0],0.5f); close_to(dng.neutral[1],1); close_to(dng.neutral[2],2.0f/3);
    /* A decoder divides raw samples by AsShotNeutral. These raw samples and
     * correction gains describe a known neutral scene, independent of a CCM. */
    close_to(0.25f/dng.neutral[0],0.5f);
    close_to(0.5f/dng.neutral[1],0.5f);
    close_to((1.0f/3)/dng.neutral[2],0.5f);
    state_proc.red=0.5f; state_proc.blue=4;
    dng=export(); close_to(dng.neutral[0],2); close_to(dng.neutral[2],0.25f);
    state_proc.red=state_proc.blue=1;
    dng=export(); for (int i=0;i<3;i++) close_to(dng.neutral[i],1);
    puts("PASS: saved DNG white balance reproduces neutral samples for nonidentity preview gains");
}
