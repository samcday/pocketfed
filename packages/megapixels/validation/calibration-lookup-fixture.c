#include <assert.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define SYSCONFDIR "sysconf"
#define DATADIR "data"

static char *fixture_home = "home";
static char *fixture_config = "xdg";

static char *fixture_getenv(const char *key)
{
        if (strcmp(key, "HOME") == 0)
                return fixture_home;
        if (strcmp(key, "XDG_CONFIG_HOME") == 0)
                return fixture_config;
        return NULL;
}

#define getenv fixture_getenv
#include "lookup-functions.c"
#undef getenv

static void touch(const char *path)
{
        FILE *file = fopen(path, "w");
        assert(file != NULL);
        assert(fclose(file) == 0);
}

static void expect(const char *path)
{
        char actual[1024] = "";
        bool found = find_calibration_by_model(sizeof(actual), actual,
                                                "google,sargo", "imx363");
        assert(found == (path != NULL));
        if (path)
                assert(strcmp(actual, path) == 0);
}

int main(void)
{
        /* A missing profile is normal on Sargo; a camera .conf is not a DCP. */
        expect(NULL);
        touch("xdg/megapixels/config/google,sargo.conf");
        expect(NULL);
        touch("xdg/megapixels/config/google,sargo,imx355.dcp");
        expect(NULL);

        /* Search each location, with user profiles taking precedence. */
        touch("data/megapixels/config/google,sargo,imx363.dcp");
        expect("data/megapixels/config/google,sargo,imx363.dcp");
        touch("sysconf/megapixels/config/google,sargo,imx363.dcp");
        expect("sysconf/megapixels/config/google,sargo,imx363.dcp");
        touch("config/google,sargo,imx363.dcp");
        expect("config/google,sargo,imx363.dcp");
        touch("xdg/megapixels/config/google,sargo,imx363.dcp");
        expect("xdg/megapixels/config/google,sargo,imx363.dcp");

        /* A truncated filename must not accidentally match a directory. */
        char tiny[4];
        assert(!find_calibration_by_model(sizeof(tiny), tiny,
                                          "google,sargo", "imx363"));

        assert(unlink("xdg/megapixels/config/google,sargo,imx363.dcp") == 0);
        assert(unlink("config/google,sargo,imx363.dcp") == 0);
        assert(unlink("sysconf/megapixels/config/google,sargo,imx363.dcp") == 0);
        assert(unlink("data/megapixels/config/google,sargo,imx363.dcp") == 0);

        fixture_config = NULL;
        touch("home/.config/megapixels/config/google,sargo,imx363.dcp");
        expect("home/.config/megapixels/config/google,sargo,imx363.dcp");
        fixture_config = "";
        expect("home/.config/megapixels/config/google,sargo,imx363.dcp");
        assert(unlink("home/.config/megapixels/config/google,sargo,imx363.dcp") == 0);
        expect(NULL);
        fixture_home = NULL;
        expect(NULL);

        puts("PASS: missing calibration, sensor-specific paths, precedence, home fallback, and bounded filenames");
        return 0;
}
