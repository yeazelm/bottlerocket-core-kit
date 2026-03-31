%global _dwz_low_mem_die_limit 0
%global debug_package %{nil}

Name: %{_cross_os}aws-clock-bound
Version: 3.0.0~alpha.1
Release: 1%{?dist}
Summary: Feed-forward time synchronization client
License: MIT OR Apache-2.0
URL: https://github.com/aws/clock-bound
Source0: https://github.com/aws/clock-bound/archive/refs/tags/3.0.0-alpha.1.tar.gz
Source1: bundled-3.0.0-alpha.1.tar.gz

Source100: clockbound.service
Source101: clockbound-sysusers.conf
Source200: clockbound-tmpfiles.conf
Source201: 80-clockbound.rules

BuildRequires: %{_cross_os}glibc-devel

%description
%{summary}.

%prep
%setup -n clock-bound-3.0.0-alpha.1 -q
%setup -T -D -a 1 -n clock-bound-3.0.0-alpha.1

%build
%set_cross_build_flags
export CARGO_HOME=%{_builddir}/.cargo
mkdir -p "${CARGO_HOME}"
cp .cargo/config.toml "${CARGO_HOME}/config.toml"

cargo build \
  --offline \
  --locked \
  --release \
  --target %{_cross_target} \
  --manifest-path clock-bound/Cargo.toml \
  --features daemon

%install
install -d %{buildroot}%{_cross_sbindir}
install -p -m 0755 target/%{_cross_target}/release/clockbound %{buildroot}%{_cross_sbindir}/clockbound

install -d %{buildroot}%{_cross_unitdir}
install -p -m 0644 %{S:100} %{buildroot}%{_cross_unitdir}/clockbound.service

install -d %{buildroot}%{_cross_sysusersdir}
install -p -m 0644 %{S:101} %{buildroot}%{_cross_sysusersdir}/clockbound.conf

install -d %{buildroot}%{_cross_tmpfilesdir}
install -p -m 0644 %{S:200} %{buildroot}%{_cross_tmpfilesdir}/clockbound.conf

install -d %{buildroot}%{_cross_udevrulesdir}
install -p -m 0644 %{S:201} %{buildroot}%{_cross_udevrulesdir}/80-clockbound.rules

%files
%license clock-bound/LICENSE.Apache-2.0 clock-bound/LICENSE.MIT
%{_cross_attribution_file}
%{_cross_sbindir}/clockbound
%{_cross_unitdir}/clockbound.service
%{_cross_sysusersdir}/clockbound.conf
%{_cross_tmpfilesdir}/clockbound.conf
%{_cross_udevrulesdir}/80-clockbound.rules

%changelog
