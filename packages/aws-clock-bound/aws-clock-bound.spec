%global _cross_first_party 1
%undefine _debugsource_packages

Name: %{_cross_os}aws-clock-bound
Version: 3.0.0~alpha.1
Release: 1%{?dist}
Summary: ClockBound daemon for clock error bound estimation
License: Apache-2.0 OR MIT
URL: https://github.com/aws/clock-bound

# Upstream source tarball
Source0: clock-bound-v3.0.0-alpha.1.tar.gz

# Workspace compatibility patches
Patch0001: 0001-workspace-compat.patch
Patch0002: 0002-source-compat.patch

Source100: clockbound.service
Source101: clockbound-sysusers.conf
Source200: clockbound-tmpfiles.conf
Source201: 80-clockbound.rules

BuildRequires: %{_cross_os}glibc-devel

%description
%{summary}.

%prep
%setup -T -c
%cargo_prep

# Extract only the clock-bound crate from the upstream tarball.
# The tarball contains a workspace with sibling crates we don't need.
# Path in tarball: clock-bound-3.0.0-alpha.1/clock-bound/clock-bound/
mkdir -p %{_builddir}/clock-bound-build
tar xf %{S:0} -C %{_builddir}/clock-bound-build \
    --strip-components=3 clock-bound-3.0.0-alpha.1/clock-bound/clock-bound

# Apply workspace compatibility patches to extracted source
patch -d %{_builddir}/clock-bound-build -p1 -i %{_sourcedir}/0001-workspace-compat.patch
patch -d %{_builddir}/clock-bound-build -p1 -i %{_sourcedir}/0002-source-compat.patch

%build
# Build the extracted upstream source using the workspace vendor directory.
# The shim in sources/ ensured all dependencies were vendored.
# We use the workspace .cargo/config.toml (set up by cargo_prep) for vendor
# and cross-compilation settings, but build from the extracted source.
cargo build \
    --offline \
    --verbose \
    --release \
    --manifest-path %{_builddir}/clock-bound-build/Cargo.toml \
    -p clock-bound \
    --features daemon \
    --target %{__cargo_target} \
    --target-dir ${HOME}/.cache/clockbound

%install
install -d %{buildroot}%{_cross_sbindir}
install -p -m 0755 ${HOME}/.cache/clockbound/%{__cargo_target}/release/clockbound %{buildroot}%{_cross_sbindir}/clockbound

install -d %{buildroot}%{_cross_unitdir}
install -p -m 0644 %{S:100} %{buildroot}%{_cross_unitdir}/clockbound.service

install -d %{buildroot}%{_cross_sysusersdir}
install -p -m 0644 %{S:101} %{buildroot}%{_cross_sysusersdir}/clockbound.conf

install -d %{buildroot}%{_cross_tmpfilesdir}
install -p -m 0644 %{S:200} %{buildroot}%{_cross_tmpfilesdir}/clockbound.conf

install -d %{buildroot}%{_cross_udevrulesdir}
install -p -m 0644 %{S:201} %{buildroot}%{_cross_udevrulesdir}/80-clockbound.rules

%cross_scan_attribution --clarify %{_builddir}/sources/clarify.toml cargo --offline --locked %{_builddir}/sources/Cargo.toml

%files
%{_cross_attribution_vendor_dir}
%{_cross_sbindir}/clockbound
%{_cross_unitdir}/clockbound.service
%{_cross_sysusersdir}/clockbound.conf
%{_cross_tmpfilesdir}/clockbound.conf
%{_cross_udevrulesdir}/80-clockbound.rules

%changelog
