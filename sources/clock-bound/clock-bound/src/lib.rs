// Dependency shim for clock-bound third-party crate.
//
// This file exists only so that `cargo generate-lockfile` can resolve
// all dependencies needed by the upstream clock-bound daemon. The real
// source is extracted from an upstream tarball during the RPM build
// and replaces this shim before compilation.
//
// Do not add real code here.
