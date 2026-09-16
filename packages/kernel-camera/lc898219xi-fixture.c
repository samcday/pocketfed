/* Hardware-free fixture. The runner inserts the real driver functions below. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint16_t u16;
typedef int16_t s16;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define container_of(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
#define CCI_REG16(r) (r)
#define cpu_to_le16(v) (v)
#define __maybe_unused __attribute__((unused))
#define V4L2_CID_FOCUS_ABSOLUTE 1
#define dev_err(dev, ...) ((void)(dev))

struct device { void *data; };
struct i2c_client { struct device dev; };
struct regmap { int unused; };
struct regulator_bulk_data { int unused; };
struct v4l2_ctrl_handler { int value; bool locked; };
struct v4l2_subdev { struct device *dev; void *data; };
struct v4l2_subdev_fh { int unused; };
struct v4l2_ctrl { struct v4l2_ctrl_handler *handler; int id; int val; };

static void *dev_get_drvdata(struct device *dev) { return dev->data; }
static void *v4l2_get_subdevdata(struct v4l2_subdev *sd) { return sd->data; }
static void usleep_range(unsigned int min, unsigned int max) { }
static void msleep(unsigned int duration) { }

static int cci_write(struct regmap *map, unsigned int reg, u16 value, void *err);
static int regulator_bulk_enable(size_t count, struct regulator_bulk_data *supplies);
static int regulator_bulk_disable(size_t count, struct regulator_bulk_data *supplies);
static int i2c_smbus_read_byte_data(struct i2c_client *client, unsigned int reg);
static int i2c_smbus_write_byte_data(struct i2c_client *client, unsigned int reg, unsigned int value);
static int pm_runtime_resume_and_get(struct device *dev);
static void pm_runtime_put_autosuspend(struct device *dev);
static int __maybe_unused v4l2_ctrl_handler_setup(struct v4l2_ctrl_handler *handler);
/* Retained so this fixture can also compile the unfixed .8 driver. */
int __v4l2_ctrl_handler_setup(struct v4l2_ctrl_handler *handler);

/* PRODUCTION_DRIVER_FUNCTIONS */

enum fault { NONE, SUPPLIES, CHIP_READ, WRONG_CHIP, WAKE_WRITE, WAKE_READ, BUSY, CONFIG_WRITE, DAC };
static struct lc898219xi lens;
static struct i2c_client client;
static enum fault fault;
static int references, regulator_references, enables, disables, setups, dac_writes;
static int wake_reads;
static bool active, suspend_pending;
static u16 last_dac;

static int regulator_bulk_enable(size_t count, struct regulator_bulk_data *supplies)
{
    assert(count == 3);
    if (fault == SUPPLIES)
        return -EIO;
    assert(regulator_references == 0);
    regulator_references++;
    enables++;
    return 0;
}

static int regulator_bulk_disable(size_t count, struct regulator_bulk_data *supplies)
{
    assert(regulator_references == 1);
    regulator_references--;
    disables++;
    return 0;
}

static int i2c_smbus_read_byte_data(struct i2c_client *client, unsigned int reg)
{
    assert(regulator_references == 1);
    if (reg == 0xf0) {
        if (fault == CHIP_READ)
            return -EREMOTEIO;
        return fault == WRONG_CHIP ? 0 : 0xa5;
    }
    assert(reg == 0xb3);
    wake_reads++;
    if (fault == WAKE_READ)
        return -EREMOTEIO;
    return fault == BUSY ? 0xe0 : 0;
}

static int i2c_smbus_write_byte_data(struct i2c_client *client, unsigned int reg, unsigned int value)
{
    assert(regulator_references == 1);
    if (reg == 0xe0) {
        assert(value == 1);
        return fault == WAKE_WRITE ? -EREMOTEIO : 0;
    }
    assert(reg == 0x8c && value == 0xe9);
    return fault == CONFIG_WRITE ? -EREMOTEIO : 0;
}

static int cci_write(struct regmap *map, unsigned int reg, u16 value, void *err)
{
    assert(reg == 0x84);
    assert(regulator_references == 1);
    assert(references > 0);
    assert(lens.ctrls.locked);
    if (fault == DAC)
        return -EREMOTEIO;
    dac_writes++;
    last_dac = value;
    return 0;
}

static int pm_runtime_resume_and_get(struct device *dev)
{
    if (!active) {
        int ret = lc898219xi_runtime_resume(dev);
        if (ret)
            return ret;
        active = true;
    }
    references++;
    suspend_pending = false;
    return 0;
}

static void pm_runtime_put_autosuspend(struct device *dev)
{
    assert(references > 0);
    references--;
    suspend_pending = references == 0;
}

static int v4l2_ctrl_handler_setup(struct v4l2_ctrl_handler *handler)
{
    assert(!handler->locked);
    handler->locked = true;
    int ret = __v4l2_ctrl_handler_setup(handler);
    handler->locked = false;
    return ret;
}

int __v4l2_ctrl_handler_setup(struct v4l2_ctrl_handler *handler)
{
    /* The unlocked helper's caller must hold the handler mutex. */
    assert(handler->locked);
    struct v4l2_ctrl ctrl = { handler, V4L2_CID_FOCUS_ABSOLUTE, handler->value };
    setups++;
    return lc898219xi_set_ctrl(&ctrl);
}

static void autosuspend(void)
{
    if (!suspend_pending)
        return;
    assert(references == 0);
    assert(lc898219xi_runtime_suspend(lens.sd.dev) == 0);
    active = false;
    suspend_pending = false;
}

static void reset(enum fault next_fault)
{
    memset(&lens, 0, sizeof(lens));
    memset(&client, 0, sizeof(client));
    lens.sd.dev = &client.dev;
    lens.sd.data = &client;
    client.dev.data = &lens.sd;
    fault = next_fault;
    references = regulator_references = enables = disables = setups = dac_writes = wake_reads = 0;
    active = suspend_pending = false;
    last_dac = 0;
}

static void set_focus(int value)
{
    struct v4l2_ctrl ctrl = { &lens.ctrls, V4L2_CID_FOCUS_ABSOLUTE, value };
    lens.ctrls.locked = true;
    assert(lc898219xi_set_ctrl(&ctrl) == 0);
    lens.ctrls.value = value;
    lens.ctrls.locked = false;
}

int main(void)
{
    reset(NONE);
    assert(lc898219xi_open(&lens.sd, NULL) == 0);
    assert(references == 1 && setups == 1 && dac_writes == 1);
    for (int value = 0; value < 4096; value += 32) {
        set_focus(value);
        assert(references == 1);
    }
    u16 focused = last_dac;
    autosuspend();
    assert(active && regulator_references == 1 && last_dac == focused);
    assert(lc898219xi_open(&lens.sd, NULL) == 0);
    assert(references == 2 && last_dac == focused);
    assert(lc898219xi_close(&lens.sd, NULL) == 0);
    autosuspend();
    assert(references == 1 && active);
    assert(lc898219xi_close(&lens.sd, NULL) == 0);
    assert(references == 0 && suspend_pending);
    /* Reopening before the deadline reuses the active device. */
    assert(lc898219xi_open(&lens.sd, NULL) == 0);
    assert(enables == 1 && !suspend_pending);
    assert(lc898219xi_close(&lens.sd, NULL) == 0);
    autosuspend();
    assert(!active && regulator_references == 0 && disables == 1);
    assert(lc898219xi_open(&lens.sd, NULL) == 0);
    assert(enables == 2 && last_dac == focused);
    assert(lc898219xi_close(&lens.sd, NULL) == 0);
    autosuspend();
    assert(references == 0 && regulator_references == 0 && disables == 2);
    puts("PASS: open, manual focus, multiple opens, idle focus retention, close, reopen");

    for (enum fault candidate = SUPPLIES; candidate <= CONFIG_WRITE; candidate++) {
        reset(candidate);
        int expected = -EREMOTEIO;
        if (candidate == SUPPLIES)
            expected = -EIO;
        else if (candidate == WRONG_CHIP)
            expected = -ENODEV;
        else if (candidate == BUSY)
            expected = -ETIMEDOUT;
        assert(lc898219xi_open(&lens.sd, NULL) == expected);
        assert(references == 0 && regulator_references == 0 && !active);
        assert(setups == 0 && dac_writes == 0);
        assert(disables == (candidate != SUPPLIES));
        if (candidate == BUSY)
            assert(wake_reads == 10);
    }
    puts("PASS: all power-on errors preserve errno, unwind rails, and skip focus writes");

    reset(DAC);
    assert(lc898219xi_open(&lens.sd, NULL) == -EREMOTEIO);
    assert(references == 0 && setups == 1 && suspend_pending);
    autosuspend();
    assert(!active && regulator_references == 0 && disables == 1);
    fault = NONE;
    assert(lc898219xi_open(&lens.sd, NULL) == 0);
    assert(lc898219xi_close(&lens.sd, NULL) == 0);
    autosuspend();
    assert(references == 0 && regulator_references == 0);
    puts("PASS: failed control setup unwinds the open reference and permits retry");
    return 0;
}
