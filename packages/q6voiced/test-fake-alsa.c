#define _GNU_SOURCE
#include <alsa/asoundlib.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static unsigned int open_calls;

static void log_line(const char *format, ...)
{
	const char *path = getenv("Q6VOICED_FAKE_LOG");
	va_list args;
	int fd;

	if (!path)
		return;

	fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
	if (fd < 0)
		return;

	va_start(args, format);
	vdprintf(fd, format, args);
	va_end(args);
	close(fd);
}

int snd_pcm_open(snd_pcm_t **pcmp, const char *name,
		 snd_pcm_stream_t stream, int mode)
{
	(void)name;
	(void)mode;
	open_calls++;
	if (open_calls <= 2) {
		log_line("open retry %u\n", open_calls);
		return -EINVAL;
	}

	*pcmp = (snd_pcm_t *)(uintptr_t)(stream + 1);
	log_line("open success %u stream %d\n", open_calls, stream);
	return 0;
}

int snd_pcm_set_params(snd_pcm_t *pcm, snd_pcm_format_t format,
		       snd_pcm_access_t access, unsigned int channels,
		       unsigned int rate, int soft_resample,
		       unsigned int latency)
{
	(void)pcm;
	(void)format;
	(void)access;
	(void)channels;
	(void)rate;
	(void)soft_resample;
	(void)latency;
	return 0;
}

int snd_pcm_prepare(snd_pcm_t *pcm)
{
	(void)pcm;
	return 0;
}

int snd_pcm_close(snd_pcm_t *pcm)
{
	log_line("close %lu\n", (unsigned long)(uintptr_t)pcm);
	return 0;
}
