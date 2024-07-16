%global tesla_major 535
%global tesla_minor 183
%global tesla_patch 01
%global tesla_ver %{tesla_major}.%{tesla_minor}.%{tesla_patch}
%if "%{?_cross_arch}" == "aarch64"
%global fm_arch sbsa
%else
%global fm_arch %{_cross_arch}
%endif

# With the split of the firmware binary from firmware/gsp.bin to firmware/gsp_ga10x.bin
# and firmware/gsp_tu10x.bin the file format changed from executable to relocatable.
# The __spec_install_post macro will by default try to strip all binary files.
# Unfortunately the strip used is not compatible with the new file format.
# Redefine strip, so that these firmware binaries do not derail the build.
%global __strip /usr/bin/true

Name: %{_cross_os}kmod-6.1-nvidia
Version: 1.0.0
Release: 1%{?dist}
Summary: NVIDIA drivers for the 6.1 kernel
# We use these licences because we only ship our own software in the main package,
# each subpackage includes the LICENSE file provided by the Licenses.toml file
License: Apache-2.0 OR MIT
URL: http://www.nvidia.com/

# NVIDIA archives from 0 to 199
# NVIDIA .run scripts for kernel and userspace drivers
Source0: https://us.download.nvidia.com/tesla/%{tesla_ver}/NVIDIA-Linux-x86_64-%{tesla_ver}.run
Source1: https://us.download.nvidia.com/tesla/%{tesla_ver}/NVIDIA-Linux-aarch64-%{tesla_ver}.run
Source2: NVidiaEULAforAWS.pdf

# fabricmanager for NVSwitch
Source10: https://developer.download.nvidia.com/compute/cuda/repos/rhel9/x86_64/nvidia-fabric-manager-%{tesla_ver}-1.x86_64.rpm
Source11: https://developer.download.nvidia.com/compute/cuda/repos/rhel9/sbsa/nvidia-fabric-manager-%{tesla_ver}-1.aarch64.rpm

# Common NVIDIA conf files from 200 to 299
Source200: nvidia-tmpfiles.conf.in
Source202: nvidia-dependencies-modules-load.conf
Source203: nvidia-fabricmanager.service
Source204: nvidia-fabricmanager.cfg

# NVIDIA tesla conf files from 300 to 399
Source300: nvidia-tesla-tmpfiles.conf
Source301: nvidia-tesla-build-config.toml.in
Source302: nvidia-tesla-path.env.in
Source303: nvidia-ld.so.conf.in

BuildRequires: %{_cross_os}glibc-devel
BuildRequires: %{_cross_os}kernel-6.1-archive

%description
%{summary}.

%package fabricmanager
Summary: NVIDIA fabricmanager config and service files
Requires: %{name}-tesla(fabricmanager)

%description fabricmanager
%{summary}.

%package tesla-%{tesla_major}
Summary: NVIDIA %{tesla_major} Tesla driver
Version: %{tesla_ver}
License: LicenseRef-NVIDIA-AWS-EULA
Requires: %{_cross_os}variant-platform(aws)
Requires: %{name}
Requires: %{name}-fabricmanager
Provides: %{name}-tesla(fabricmanager)

%description tesla-%{tesla_major}
%{summary}

%prep
# Extract nvidia sources with `-x`, otherwise the script will try to install
# the driver in the current run
sh %{_sourcedir}/NVIDIA-Linux-%{_cross_arch}-%{tesla_ver}.run -x

# Extract fabricmanager from the rpm via cpio rather than `%%setup` since the
# correct source is architecture-dependent.
mkdir fabricmanager-linux-%{fm_arch}-%{tesla_ver}-archive
rpm2cpio %{_sourcedir}/nvidia-fabric-manager-%{tesla_ver}-1.%{_cross_arch}.rpm | cpio -idmV -D fabricmanager-linux-%{fm_arch}-%{tesla_ver}-archive

# Add the license.
install -p -m 0644 %{S:2} .

%global kernel_sources %{_builddir}/kernel-devel
tar -xf %{_cross_datadir}/bottlerocket/kernel-devel.tar.xz

%build
pushd NVIDIA-Linux-%{_cross_arch}-%{tesla_ver}/kernel-open

# This recipe was based in the NVIDIA yum/dnf specs:
# https://github.com/NVIDIA/yum-packaging-precompiled-kmod

# We set IGNORE_CC_MISMATCH even though we are using the same compiler used to compile the kernel, if
# we don't set this flag the compilation fails
make %{?_smp_mflags} ARCH=%{_cross_karch} IGNORE_CC_MISMATCH=1 SYSSRC=%{kernel_sources} CC=%{_cross_target}-gcc LD=%{_cross_target}-ld

%{_cross_target}-strip -g --strip-unneeded nvidia/nv-interface.o
%{_cross_target}-strip -g --strip-unneeded nvidia-uvm.o
%{_cross_target}-strip -g --strip-unneeded nvidia-drm.o
%{_cross_target}-strip -g --strip-unneeded nvidia-peermem/nvidia-peermem.o
%{_cross_target}-strip -g --strip-unneeded nvidia-modeset/nv-modeset-interface.o

# We delete these files since we just stripped the input .o files above, and
# will be build at runtime in the host
rm nvidia{,-modeset,-peermem}.o

# Delete the .ko files created in make command, just to be safe that we
# don't include any linked module in the base image
rm nvidia{,-modeset,-peermem,-drm}.ko

popd

%install
install -d %{buildroot}%{_cross_libexecdir}
install -d %{buildroot}%{_cross_libdir}
install -d %{buildroot}%{_cross_tmpfilesdir}
install -d %{buildroot}%{_cross_unitdir}
install -d %{buildroot}%{_cross_factorydir}%{_cross_sysconfdir}/{drivers,ld.so.conf.d}

KERNEL_VERSION=$(cat %{kernel_sources}/include/config/kernel.release)
sed \
  -e "s|__KERNEL_VERSION__|${KERNEL_VERSION}|" \
  -e "s|__PREFIX__|%{_cross_prefix}|" %{S:200} > nvidia.conf
install -p -m 0644 nvidia.conf %{buildroot}%{_cross_tmpfilesdir}

# Install modules-load.d drop-in to autoload required kernel modules
install -d %{buildroot}%{_cross_libdir}/modules-load.d
install -p -m 0644 %{S:202} %{buildroot}%{_cross_libdir}/modules-load.d/nvidia-dependencies.conf

# NVIDIA fabric manager service unit and config
install -p -m 0644 %{S:203} %{buildroot}%{_cross_unitdir}
install -d %{buildroot}%{_cross_factorydir}%{_cross_sysconfdir}/nvidia
install -p -m 0644 %{S:204} %{buildroot}%{_cross_factorydir}%{_cross_sysconfdir}/nvidia/fabricmanager.cfg

# Begin NVIDIA tesla driver
pushd NVIDIA-Linux-%{_cross_arch}-%{tesla_ver}
# We install bins and libs in a versioned directory to prevent collisions with future drivers versions
install -d %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
install -d %{buildroot}%{_cross_libdir}/nvidia/tesla
install -d %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install -d %{buildroot}%{_cross_factorydir}/nvidia/tesla

install -m 0644 %{S:300} %{buildroot}%{_cross_tmpfilesdir}/nvidia-tesla.conf
sed -e 's|__NVIDIA_MODULES__|%{_cross_datadir}/nvidia/tesla/module-objects.d/|' %{S:301} > \
  nvidia-tesla.toml
install -m 0644 nvidia-tesla.toml %{buildroot}%{_cross_factorydir}%{_cross_sysconfdir}/drivers
# Install nvidia-path environment file, will be used as a drop-in for containerd.service since
# libnvidia-container locates and mounts helper binaries into the containers from either
# `PATH` or `NVIDIA_PATH`
sed -e 's|__NVIDIA_BINDIR__|%{_cross_libexecdir}/nvidia/tesla/bin|' %{S:302} > nvidia-path.env
install -m 0644 nvidia-path.env %{buildroot}%{_cross_factorydir}/nvidia/tesla
# We need to add `_cross_libdir` to the paths loaded by the ldconfig service
# because libnvidia-container uses the `ldcache` file created by the service, to locate and mount the
# libraries into the containers
sed -e 's|__LIBDIR__|%{_cross_libdir}|' %{S:303} > nvidia-tesla.conf
install -m 0644 nvidia-tesla.conf %{buildroot}%{_cross_factorydir}%{_cross_sysconfdir}/ld.so.conf.d/

# driver
install kernel-open/nvidia.mod.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia/nv-interface.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia/nv-kernel.o_binary %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d/nv-kernel.o

# uvm
install kernel-open/nvidia-uvm.mod.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia-uvm.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d

# modeset
install kernel-open/nvidia-modeset.mod.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia-modeset/nv-modeset-interface.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia-modeset/nv-modeset-kernel.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d

# peermem
install kernel-open/nvidia-peermem.mod.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia-peermem/nvidia-peermem.o %{buildroot}%{_cross_datadir}/nvidia/tesla/module-objects.d

# drm
install kernel-open/nvidia-drm.mod.o %{buildroot}/%{_cross_datadir}/nvidia/tesla/module-objects.d
install kernel-open/nvidia-drm.o %{buildroot}/%{_cross_datadir}/nvidia/tesla/module-objects.d

# Binaries
install -m 755 nvidia-smi %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
install -m 755 nvidia-debugdump %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
install -m 755 nvidia-cuda-mps-control %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
install -m 755 nvidia-cuda-mps-server %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
%if "%{_cross_arch}" == "x86_64"
install -m 755 nvidia-ngx-updater %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
%endif

# We install all the libraries, and filter them out in the 'files' section, so we can catch
# when new libraries are added
install -m 755 *.so* %{buildroot}/%{_cross_libdir}/nvidia/tesla/

# This library has the same SONAME as libEGL.so.1.1.0, this will cause collisions while
# the symlinks are created. For now, we only symlink libEGL.so.1.1.0.
EXCLUDED_LIBS="libEGL.so.%{tesla_ver}"

for lib in $(find . -maxdepth 1 -type f -name 'lib*.so.*' -printf '%%P\n'); do
  [[ "${EXCLUDED_LIBS}" =~ "${lib}" ]] && continue
  soname="$(%{_cross_target}-readelf -d "${lib}" | awk '/SONAME/{print $5}' | tr -d '[]')"
  [ -n "${soname}" ] || continue
  [ "${lib}" == "${soname}" ] && continue
  ln -s "${lib}" %{buildroot}/%{_cross_libdir}/nvidia/tesla/"${soname}"
done

# Include the firmware file for GSP support
install -d %{buildroot}%{_cross_libdir}/firmware/nvidia/%{tesla_ver}
install -p -m 0644 firmware/gsp_ga10x.bin %{buildroot}%{_cross_libdir}/firmware/nvidia/%{tesla_ver}
install -p -m 0644 firmware/gsp_tu10x.bin %{buildroot}%{_cross_libdir}/firmware/nvidia/%{tesla_ver}

popd

# Begin NVIDIA fabric manager binaries and topologies
pushd fabricmanager-linux-%{fm_arch}-%{tesla_ver}-archive
install -p -m 0755 usr/bin/nv-fabricmanager %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin
install -p -m 0755 usr/bin/nvswitch-audit %{buildroot}%{_cross_libexecdir}/nvidia/tesla/bin

install -d %{buildroot}%{_cross_datadir}/nvidia/tesla/nvswitch
for t in usr/share/nvidia/nvswitch/*_topology ; do
  install -p -m 0644 "${t}" %{buildroot}%{_cross_datadir}/nvidia/tesla/nvswitch
done

popd

%files
%{_cross_attribution_file}
%dir %{_cross_libexecdir}/nvidia
%dir %{_cross_libdir}/nvidia
%dir %{_cross_datadir}/nvidia
%dir %{_cross_libdir}/modules-load.d
%dir %{_cross_factorydir}%{_cross_sysconfdir}/drivers
%dir %{_cross_factorydir}%{_cross_sysconfdir}/nvidia
%{_cross_tmpfilesdir}/nvidia.conf
%{_cross_libdir}/modules-load.d/nvidia-dependencies.conf

%files tesla-%{tesla_major}
%license NVidiaEULAforAWS.pdf
%license fabricmanager-linux-%{fm_arch}-%{tesla_ver}-archive/usr/share/doc/nvidia-fabricmanager/third-party-notices.txt
%dir %{_cross_datadir}/nvidia/tesla
%dir %{_cross_libexecdir}/nvidia/tesla/bin
%dir %{_cross_libdir}/nvidia/tesla
%dir %{_cross_libdir}/firmware/nvidia/%{tesla_ver}
%dir %{_cross_datadir}/nvidia/tesla/module-objects.d
%dir %{_cross_factorydir}/nvidia/tesla

# Binaries
%{_cross_libexecdir}/nvidia/tesla/bin/nvidia-debugdump
%{_cross_libexecdir}/nvidia/tesla/bin/nvidia-smi
%{_cross_libexecdir}/nvidia/tesla/bin/nv-fabricmanager
%{_cross_libexecdir}/nvidia/tesla/bin/nvswitch-audit

# nvswitch topologies
%dir %{_cross_datadir}/nvidia/tesla/nvswitch
%{_cross_datadir}/nvidia/tesla/nvswitch/dgxa100_hgxa100_topology
%{_cross_datadir}/nvidia/tesla/nvswitch/dgx2_hgx2_topology
%{_cross_datadir}/nvidia/tesla/nvswitch/dgxh100_hgxh100_topology
%{_cross_datadir}/nvidia/tesla/nvswitch/dgxh800_hgxh800_topology

# Configuration files
%{_cross_factorydir}%{_cross_sysconfdir}/drivers/nvidia-tesla.toml
%{_cross_factorydir}%{_cross_sysconfdir}/ld.so.conf.d/nvidia-tesla.conf
%{_cross_factorydir}/nvidia/tesla/nvidia-path.env

# driver
%{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia.mod.o
%{_cross_datadir}/nvidia/tesla/module-objects.d/nv-interface.o
%{_cross_datadir}/nvidia/tesla/module-objects.d/nv-kernel.o

# uvm
%{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-uvm.mod.o
%{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-uvm.o

# modeset
%{_cross_datadir}/nvidia/tesla/module-objects.d/nv-modeset-interface.o
%{_cross_datadir}/nvidia/tesla/module-objects.d/nv-modeset-kernel.o
%{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-modeset.mod.o

# tmpfiles
%{_cross_tmpfilesdir}/nvidia-tesla.conf

# We only install the libraries required by all the DRIVER_CAPABILITIES, described here:
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/user-guide.html#driver-capabilities

# Utility libs
%{_cross_libdir}/nvidia/tesla/libnvidia-api.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-ml.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-ml.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-cfg.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-cfg.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-nvvm.so.4
%{_cross_libdir}/nvidia/tesla/libnvidia-nvvm.so.%{tesla_ver}

# Compute libs
%{_cross_libdir}/nvidia/tesla/libcuda.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libcuda.so.1
%{_cross_libdir}/nvidia/tesla/libcudadebugger.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libcudadebugger.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-opencl.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-opencl.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-ptxjitcompiler.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-ptxjitcompiler.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-allocator.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-allocator.so.1
%{_cross_libdir}/nvidia/tesla/libOpenCL.so.1.0.0
%{_cross_libdir}/nvidia/tesla/libOpenCL.so.1
%if "%{_cross_arch}" == "x86_64"
%{_cross_libdir}/nvidia/tesla/libnvidia-pkcs11.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-pkcs11-openssl3.so.%{tesla_ver}
%endif

# Video libs
%{_cross_libdir}/nvidia/tesla/libvdpau_nvidia.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libvdpau_nvidia.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-encode.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-encode.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-opticalflow.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-opticalflow.so.1
%{_cross_libdir}/nvidia/tesla/libnvcuvid.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvcuvid.so.1

# Graphics libs
%{_cross_libdir}/nvidia/tesla/libnvidia-eglcore.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-glcore.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-tls.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-glsi.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-rtcore.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-fbc.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-fbc.so.1
%{_cross_libdir}/nvidia/tesla/libnvoptix.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvoptix.so.1
%{_cross_libdir}/nvidia/tesla/libnvidia-vulkan-producer.so.%{tesla_ver}

# Graphics GLVND libs
%{_cross_libdir}/nvidia/tesla/libnvidia-glvkspirv.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libGLX_nvidia.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libGLX_nvidia.so.0
%{_cross_libdir}/nvidia/tesla/libEGL_nvidia.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libEGL_nvidia.so.0
%{_cross_libdir}/nvidia/tesla/libGLESv2_nvidia.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libGLESv2_nvidia.so.2
%{_cross_libdir}/nvidia/tesla/libGLESv1_CM_nvidia.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libGLESv1_CM_nvidia.so.1

# Graphics compat
%{_cross_libdir}/nvidia/tesla/libEGL.so.1.1.0
%{_cross_libdir}/nvidia/tesla/libEGL.so.1
%{_cross_libdir}/nvidia/tesla/libEGL.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libGL.so.1.7.0
%{_cross_libdir}/nvidia/tesla/libGL.so.1
%{_cross_libdir}/nvidia/tesla/libGLESv1_CM.so.1.2.0
%{_cross_libdir}/nvidia/tesla/libGLESv1_CM.so.1
%{_cross_libdir}/nvidia/tesla/libGLESv2.so.2.1.0
%{_cross_libdir}/nvidia/tesla/libGLESv2.so.2

# NGX
%{_cross_libdir}/nvidia/tesla/libnvidia-ngx.so.%{tesla_ver}
%{_cross_libdir}/nvidia/tesla/libnvidia-ngx.so.1

# Firmware
%{_cross_libdir}/firmware/nvidia/%{tesla_ver}/gsp_ga10x.bin
%{_cross_libdir}/firmware/nvidia/%{tesla_ver}/gsp_tu10x.bin

# Neither nvidia-peermem nor nvidia-drm are included in driver container images, we exclude them
# for now, and we will add them if requested
%exclude %{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-peermem.mod.o
%exclude %{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-peermem.o
%exclude %{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-drm.mod.o
%exclude %{_cross_datadir}/nvidia/tesla/module-objects.d/nvidia-drm.o
%exclude %{_cross_libexecdir}/nvidia/tesla/bin/nvidia-cuda-mps-control
%exclude %{_cross_libexecdir}/nvidia/tesla/bin/nvidia-cuda-mps-server
%if "%{_cross_arch}" == "x86_64"
%exclude %{_cross_libexecdir}/nvidia/tesla/bin/nvidia-ngx-updater
%endif

# None of these libraries are required by libnvidia-container, so they
# won't be used by a containerized workload
%exclude %{_cross_libdir}/nvidia/tesla/libGLX.so.0
%exclude %{_cross_libdir}/nvidia/tesla/libGLdispatch.so.0
%exclude %{_cross_libdir}/nvidia/tesla/libOpenGL.so.0
%exclude %{_cross_libdir}/nvidia/tesla/libglxserver_nvidia.so.%{tesla_ver}
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-gtk2.so.%{tesla_ver}
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-gtk3.so.%{tesla_ver}
%exclude %{_cross_libdir}/nvidia/tesla/nvidia_drv.so
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-egl-wayland.so.1
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-egl-gbm.so.1
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-egl-gbm.so.1.1.0
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-egl-wayland.so.1.1.11
%exclude %{_cross_libdir}/nvidia/tesla/libnvidia-wayland-client.so.%{tesla_ver}

%files fabricmanager
%{_cross_factorydir}%{_cross_sysconfdir}/nvidia/fabricmanager.cfg
%{_cross_unitdir}/nvidia-fabricmanager.service
