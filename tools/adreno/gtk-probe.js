#!/usr/bin/gjs
// Small, synthetic GTK4 rendering workload for pocketfed#80.
imports.gi.versions.Gtk = '4.0';
imports.gi.versions.Gdk = '4.0';
const {Gdk, Gio, GLib, Gtk} = imports.gi;

const app = new Gtk.Application({
    application_id: 'org.pocketfed.AdrenoProbe',
    flags: Gio.ApplicationFlags.NON_UNIQUE,
});

app.connect('activate', () => {
    const css = new Gtk.CssProvider();
    css.load_from_string(`
        .probe { background: linear-gradient(135deg, #24578a, #a24076);
                 border-radius: 18px; padding: 12px; margin: 4px;
                 box-shadow: 2px 3px 6px alpha(black, 0.5); color: white; }
    `);
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION);

    const grid = new Gtk.Grid({row_spacing: 8, column_spacing: 8});
    const labels = [];
    for (let i = 0; i < 12; i++) {
        const label = new Gtk.Label({label: `Tile ${i}`, hexpand: true, vexpand: true});
        label.add_css_class('probe');
        grid.attach(label, i % 3, Math.floor(i / 3), 1, 1);
        labels.push(label);
    }
    const window = new Gtk.ApplicationWindow({
        application: app, title: 'Adreno GTK probe',
        default_width: 640, default_height: 480, child: grid,
    });
    window.present();

    let tick = 0;
    const timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 200, () => {
        tick++;
        labels.forEach((label, i) => {
            label.set_label(`Tile ${i}: ${tick}`);
            label.set_opacity((tick + i) % 2 ? 0.55 : 1.0);
        });
        if (tick % 50 === 0)
            print(`probe tick=${tick}`);
        if (tick === 450) {
            print('probe complete');
            app.quit();
            return GLib.SOURCE_REMOVE;
        }
        return GLib.SOURCE_CONTINUE;
    });
    window.connect('close-request', () => {
        GLib.source_remove(timer);
        return false;
    });
});

app.run([]);
