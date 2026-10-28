# PocketFed development

Use mkosi directly, without a command wrapper.
`mkosi.postoutput` runs short end-to-end checks on the finished directory image and prints their runtime.
Keep these checks focused on observable image behavior.
If intended behavior changes, update the corresponding checks.
Use local builds or GitHub Actions to run the checks.
Report which checks actually ran.

Do not edit README files. Sam writes them.
