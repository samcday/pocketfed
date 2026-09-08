# Proposed next milestone: a real whole-word swipe

The next proposed goal is opt-in English-US, single-finger swipe input for a
new whole word in Stevia. Releasing the gesture shows ranked candidates in the
existing bar; explicit selection commits one word through existing Wayland
text handling. Ordinary tap typing remains available. This is a proposed
milestone, not a feature already enabled or work started in a new task.

Stevia should own touch arbitration and export the actual allocated key
rectangles with a bounded touch trace. Swiping must be distinguished before
Stevia emits each crossed key. Second contact, focus loss and layout changes
must cancel a gesture; existing taps, long presses and space-cursor behavior
must retain their behavior.

The proposed first implementation runs Drift Type beside Patricia inside
Verbisage. One request contains a completed trace and geometry snapshot; one
reply contains ranked words. Existing text-only `Complete` cannot decode a
gesture. Avoid a D-Bus call per dictionary candidate or trie node. Geometry is
a shared interface, so a wholesale layout rewrite is unnecessary.

At the packaged Drift revision `f63256a5bb973b10a4e11e190cfbb105fc89da0a`,
`InputPoint`, `RectKeyLayout` and `resolve` support this shape. Prefix/suffix
handling for mixed tap/swipe composition is documented as unimplemented, so
the initial gesture starts a new word. Its dictionary trait borrows word
strings while Patricia produces owned strings. A retained-word adapter and
candidate pruning need measurement for memory, latency and ranking quality.

Start with a small deterministic replay set, then real deliberate phone swipes.
Acceptance means useful top-three candidates, exactly one selected commit,
no stray letters from crossed keys and no tap-typing regression. Measure real
phone latency in an isolated trial before enabling the feature in regular use.

Meanwhile, daily-use reports should identify the app/field, typed word, expected
suggestion and actual candidates when practical. Improvements should generalize
across a small corpus; a successful `helo` example is not a general accuracy
claim. Current input does not add learning, next-word suggestions or automatic
correction. Upstream submission restrictions remain as documented in the
[Drift packaging notes](../drift-type/README.md).
