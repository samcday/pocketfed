/* Disposable text field for reproducing Wayland OSK preedit resets. */
#include <gtk/gtk.h>

static void
preedit_changed (GtkTextView *view, const char *text, gpointer data)
{
  g_print ("PREEDIT: %s\n", text);
}

static void
buffer_changed (GtkTextBuffer *buffer, gpointer data)
{
  GtkTextIter start, end;
  g_autofree char *text = NULL;

  gtk_text_buffer_get_bounds (buffer, &start, &end);
  text = gtk_text_buffer_get_text (buffer, &start, &end, FALSE);
  g_print ("BUFFER: %s\n", text);
}

static void
activate (GtkApplication *app, gpointer data)
{
  GtkWidget *window = gtk_application_window_new (app);
  GtkWidget *view = gtk_text_view_new ();

  gtk_window_set_title (GTK_WINDOW (window), "PocketFed preedit test");
  gtk_window_set_default_size (GTK_WINDOW (window), 360, 420);
  gtk_text_view_set_wrap_mode (GTK_TEXT_VIEW (view), GTK_WRAP_WORD_CHAR);
  gtk_text_view_set_input_hints (GTK_TEXT_VIEW (view), GTK_INPUT_HINT_WORD_COMPLETION);
  g_signal_connect (view, "preedit-changed", G_CALLBACK (preedit_changed), NULL);
  g_signal_connect (gtk_text_view_get_buffer (GTK_TEXT_VIEW (view)),
                    "changed", G_CALLBACK (buffer_changed), NULL);
  gtk_window_set_child (GTK_WINDOW (window), view);
  gtk_window_present (GTK_WINDOW (window));
  gtk_widget_grab_focus (view);
}

int
main (int argc, char **argv)
{
  g_autoptr (GtkApplication) app =
    gtk_application_new ("org.pocketfed.PreeditTest", G_APPLICATION_NON_UNIQUE);

  g_signal_connect (app, "activate", G_CALLBACK (activate), NULL);
  return g_application_run (G_APPLICATION (app), argc, argv);
}
