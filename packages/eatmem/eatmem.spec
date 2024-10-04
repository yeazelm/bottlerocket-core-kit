%global _cross_first_party 1
%global workspace_name eatmem

Name: %{_cross_os}%{workspace_name}
Version: 0.0
Release: 0%{?dist}
Summary: Memory eater for pressure tests
License: Apache-2.0 OR MIT
Source1: eatmem.service
BuildRequires: %{_cross_os}glibc-devel

%description
%{summary}.

%prep
%setup -T -c
cp -r %{_builddir}/sources/%{workspace_name}/* .

%build
%set_cross_go_flags
# We don't set `-Wl,-z,now`, because the binary uses lazy loading
# to load the NVIDIA libraries in the host
export CGO_LDFLAGS="-Wl,-z,relro -Wl,--export-dynamic"
export GOLDFLAGS="-compressdwarf=false -linkmode=external -extldflags '${CGO_LDFLAGS}'"
go build -ldflags="${GOLDFLAGS}" -o eatmem ./eatmem.go

%install
install -d %{buildroot}%{_cross_bindir}
install -p -m 0755 eatmem %{buildroot}%{_cross_bindir}

install -d %{buildroot}%{_cross_unitdir}
install -D -p -m 0644 %{S:1} %{buildroot}%{_cross_unitdir}


%files
%{_cross_bindir}/eatmem
%{_cross_unitdir}/eatmem.service
