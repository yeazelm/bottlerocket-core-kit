Name: %{_cross_os}kmod-6.1-nvidia-open
Version: 535.183.01
Release: 1%{?dist}
Summary: NVIDIA open source drivers for the 6.1 kernel
License: MIT OR GPL-2.0-only
URL: https://awsdocs-neuron.readthedocs-hosted.com/en/latest/

Source0: https://github.com/NVIDIA/open-gpu-kernel-modules/archive/refs/tags/%{version}.tar.gz
Patch0001: 0001-Add-cross-compile-to-args.patch

BuildRequires: %{_cross_os}glibc-devel
BuildRequires: %{_cross_os}kernel-6.1-archive

%description
%{summary}.

%prep
tar -xf %{SOURCE0}
tar -xf %{_cross_datadir}/bottlerocket/kernel-devel.tar.xz
%autopatch -p1

%global nvidia_sources open-gpu-kernel-modules-%{version}
%global kernel_sources %{_builddir}/kernel-devel


%build 
export ARCH="%{_cross_karch}"
export CROSS_COMPILE="%{_cross_target}-"
export CC=%{_cross_target}-gcc 
export LD=%{_cross_target}-ld 
export AR=%{_cross_target}-ar 
export CXX=%{_cross_target}-g++ 
export OBJCOPY=%{_cross_target}-objcopy 
pushd %{_builddir}/%{nvidia_sources}
mkdir -p %{nvidia_sources}/build
make \
  SYSSRC=%{kernel_sources} \
  CC=%{_cross_target}-gcc \
  LD=%{_cross_target}-ld \
  AR=%{_cross_target}-ar \
  CXX=%{_cross_target}-g++ \
  OBJCOPY=%{_cross_target}-objcopy \
  ARCH="%{_cross_karch}" \
  CROSS_COMPILE=%{_cross_target}- \
  modules \
  %{nil}

popd

%install
pushd %{_builddir}/%{nvidia_sources}
export KVER="$(cat %{kernel_sources}/include/config/kernel.release)"
export KMODDIR="%{_cross_libdir}/modules/${KVER}/extra"
install -d "%{buildroot}${KMODDIR}"
install -p -m 0644 kernel-open/nvidia.ko "%{buildroot}${KMODDIR}"
install -p -m 0644 kernel-open/nvidia-drm.ko "%{buildroot}${KMODDIR}"
install -p -m 0644 kernel-open/nvidia-modeset.ko "%{buildroot}${KMODDIR}"
install -p -m 0644 kernel-open/nvidia-peermem.ko "%{buildroot}${KMODDIR}"
install -p -m 0644 kernel-open/nvidia-uvm.ko "%{buildroot}${KMODDIR}"
popd

%files
%license %{nvidia_sources}/COPYING
%{_cross_attribution_file}
%{_cross_libdir}/modules/6.1.94/extra/nvidia.ko
%{_cross_libdir}/modules/6.1.94/extra/nvidia-drm.ko
%{_cross_libdir}/modules/6.1.94/extra/nvidia-modeset.ko
%{_cross_libdir}/modules/6.1.94/extra/nvidia-peermem.ko
%{_cross_libdir}/modules/6.1.94/extra/nvidia-uvm.ko
