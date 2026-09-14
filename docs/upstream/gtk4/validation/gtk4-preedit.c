/* Disposable text field for reproducing Wayland OSK preedit resets. */
#include <gtk/gtk.h>

static gboolean
perform_action (gpointer data)
{
  GtkTextView *view = data;
  const char *action = g_getenv ("IME_TEST_ACTION");

  g_print ("ACTION: %s\n", action);
  if (g_strcmp0 (action, "reset") == 0)
    gtk_text_view_reset_im_context (view);
  else if (g_strcmp0 (action, "layout") == 0)
    gtk_widget_set_margin_start (GTK_WIDGET (view), 40);
  else if (g_strcmp0 (action, "cursor") == 0)
    g_signal_emit_by_name (view, "move-cursor", GTK_MOVEMENT_BUFFER_ENDS, -1, FALSE);
  else if (g_strcmp0 (action, "focus") == 0)
    gtk_widget_grab_focus (g_object_get_data (G_OBJECT (view), "other-widget"));
  return G_SOURCE_REMOVE;
}

static void
preedit_changed (GtkTextView *view, const char *text, gpointer data)
{
  static gboolean scheduled = FALSE;

  g_print ("PREEDIT: %s\n", text);
  if (text[0] && g_getenv ("IME_TEST_ACTION") && !scheduled)
    {
      scheduled = TRUE;
      g_timeout_add (200, perform_action, view);
    }
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
  GtkWidget *box = gtk_box_new (GTK_ORIENTATION_VERTICAL, 0);
  GtkWidget *other = gtk_button_new_with_label ("Focus target");

  if (g_strcmp0 (g_getenv ("IME_TEST_ACTION"), "cursor") == 0)
    gtk_text_buffer_set_text (gtk_text_view_get_buffer (GTK_TEXT_VIEW (view)), "prefix ", -1);
  gtk_widget_set_vexpand (view, TRUE);
  gtk_box_append (GTK_BOX (box), view);
  gtk_box_append (GTK_BOX (box), other);
  g_object_set_data (G_OBJECT (view), "other-widget", other);

  gtk_window_set_title (GTK_WINDOW (window), "PocketFed preedit test");
  gtk_window_set_default_size (GTK_WINDOW (window), 360, 420);
  gtk_text_view_set_wrap_mode (GTK_TEXT_VIEW (view), GTK_WRAP_WORD_CHAR);
  gtk_text_view_set_input_hints (GTK_TEXT_VIEW (view), GTK_INPUT_HINT_WORD_COMPLETION);
  g_signal_connect (view, "preedit-changed", G_CALLBACK (preedit_changed), NULL);
  g_signal_connect (gtk_text_view_get_buffer (GTK_TEXT_VIEW (view)),
                    "changed", G_CALLBACK (buffer_changed), NULL);
  gtk_window_set_child (GTK_WINDOW (window), box);
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
