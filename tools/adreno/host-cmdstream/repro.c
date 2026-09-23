/* HOST-ONLY reproducer of pocketfed#80 minimal pair (calls 6076 + 6119 of r3.trace)
 * under the freedreno drm-shim (a306).  Renders nothing real: we only want the
 * command stream that fd3 emits.  Usage: repro <p3|p7> */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char *slurp(const char *p) {
   FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(1); }
   fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
   char *b = malloc(n + 1); if (fread(b, 1, n, f) != (size_t)n) exit(1);
   b[n] = 0; fclose(f); return b;
}
static GLuint mkshader(GLenum type, const char *path) {
   char *src = slurp(path);
   GLuint s = glCreateShader(type);
   glShaderSource(s, 1, (const GLchar *const *)&src, NULL);
   glCompileShader(s);
   GLint ok = 0; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
   if (!ok) { char log[16384]; glGetShaderInfoLog(s, sizeof log, NULL, log);
              fprintf(stderr, "compile %s failed:\n%s\n", path, log); exit(1); }
   free(src); return s;
}
static const char *attribs[] = {
   "in_bounds","in_start_end","in_color0","in_color1","in_color2","in_color3",
   "in_color4","in_color5","in_color6","in_offsets0","in_offsets1",
   "in_hints0","in_hints1" };

int main(int argc, char **argv) {
   const char *tag = argc > 1 ? argv[1] : "p7";
   char vs_path[256], fs_path[256];
   snprintf(vs_path, sizeof vs_path, "%s/shaders/%s_vs.glsl", getenv("REPRO_DIR"), tag);
   snprintf(fs_path, sizeof fs_path, "%s/shaders/%s_fs.glsl", getenv("REPRO_DIR"), tag);

   EGLDisplay dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
   if (dpy == EGL_NO_DISPLAY) { fprintf(stderr, "no display\n"); return 1; }
   EGLint maj, min;
   if (!eglInitialize(dpy, &maj, &min)) { fprintf(stderr, "eglInitialize failed\n"); return 1; }
   fprintf(stderr, "EGL %d.%d vendor=%s\n", maj, min, eglQueryString(dpy, EGL_VENDOR));
   eglBindAPI(EGL_OPENGL_ES_API);
   EGLint cfg_attr[] = { EGL_SURFACE_TYPE, EGL_PBUFFER_BIT,
                         EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
                         EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
                         EGL_ALPHA_SIZE, 8, EGL_NONE };
   EGLConfig cfg; EGLint n = 0;
   if (!eglChooseConfig(dpy, cfg_attr, &cfg, 1, &n) || n < 1) {
      fprintf(stderr, "no config\n"); return 1; }
   EGLint ctx_attr[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE };
   EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, ctx_attr);
   if (!ctx) { fprintf(stderr, "no context\n"); return 1; }
   if (!eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
      fprintf(stderr, "makecurrent failed 0x%x\n", eglGetError()); return 1; }
   fprintf(stderr, "GL_RENDERER=%s\nGL_VERSION=%s\n", glGetString(GL_RENDERER), glGetString(GL_VERSION));

   /* 1280x688 RGBA8 render target, like the trace's window surface */
   GLuint tex, fbo;
   glGenTextures(1, &tex);
   glBindTexture(GL_TEXTURE_2D, tex);
   glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA8, 1280, 688);
   glGenFramebuffers(1, &fbo);
   glBindFramebuffer(GL_FRAMEBUFFER, fbo);
   glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0);
   if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
      fprintf(stderr, "fbo incomplete\n"); return 1; }

   GLuint vao; glGenVertexArrays(1, &vao); glBindVertexArray(vao);
   GLuint ubo, vbo;
   glGenBuffers(1, &ubo);
   glBindBuffer(GL_UNIFORM_BUFFER, ubo);
   glBufferData(GL_UNIFORM_BUFFER, 16384, NULL, GL_STATIC_DRAW);   /* call 4264 */
   glGenBuffers(1, &vbo);
   glBindBuffer(GL_ARRAY_BUFFER, vbo);
   glBufferData(GL_ARRAY_BUFFER, 131072, NULL, GL_STATIC_DRAW);    /* call 4267 */

   GLuint vs = mkshader(GL_VERTEX_SHADER, vs_path);
   GLuint fs = mkshader(GL_FRAGMENT_SHADER, fs_path);
   GLuint prog = glCreateProgram();
   glAttachShader(prog, vs); glAttachShader(prog, fs);
   for (int i = 0; i < 13; i++) glBindAttribLocation(prog, i, attribs[i]);
   glLinkProgram(prog);
   GLint ok = 0; glGetProgramiv(prog, GL_LINK_STATUS, &ok);
   if (!ok) { char log[16384]; glGetProgramInfoLog(prog, sizeof log, NULL, log);
              fprintf(stderr, "link failed:\n%s\n", log); return 1; }
   glUseProgram(prog);

   GLuint blk = glGetUniformBlockIndex(prog, "PushConstants");
   if (blk != GL_INVALID_INDEX) glUniformBlockBinding(prog, blk, 0);
   fprintf(stderr, "PushConstants block index = %u\n", blk);

   glViewport(0, 0, 1280, 688);          /* call 4066 */
   glDisable(GL_DEPTH_TEST);
   glEnable(GL_SCISSOR_TEST);
   glEnable(GL_BLEND);
   glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);

   /* --- flush everything set up so far into its own batch --- */
   glFlush(); glFinish();
   fprintf(stderr, "=== setup done, minimal pair follows ===\n");

   /* call 6074/6075/6076: scissored clear */
   glScissor(1258, 4, 22, 641);
   glClearColor(0.9647059f, 0.9607843f, 0.9568627f, 1.0f);
   glClear(GL_COLOR_BUFFER_BIT);
   /* call 6078: UBO range */
   glBindBufferRange(GL_UNIFORM_BUFFER, 0, ubo, 576, 160);
   /* call 6079 */
   glScissor(1258, 4, 22, 641);
   /* calls 6080..6118 */
   for (int i = 0; i < 13; i++) {
      glEnableVertexAttribArray(i);
      glVertexAttribDivisor(i, 1);
      glVertexAttribPointer(i, 4, GL_FLOAT, GL_FALSE, 208,
                            (const void *)(uintptr_t)(0x820 + 0x10 * i));
   }
   /* call 6119 */
   glDrawArraysInstanced(GL_TRIANGLES, 0, 6, 1);

   glFlush(); glFinish();
   fprintf(stderr, "=== done, gl error = 0x%x ===\n", glGetError());
   return 0;
}
