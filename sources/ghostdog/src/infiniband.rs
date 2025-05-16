use crate::error;
use crate::error::Result;
use snafu::{ensure, ResultExt};
use std::ffi::OsString;
use std::ops::BitAnd;
use std::path::Path;
use std::str::FromStr;
use std::{fs, str};

const SYS_CLASS_DIR: &str = "/sys/class";
const SW_MNG_CLASS: &str = "infiniband";
const SW_MNG_VALUE: &str = "SW_MNG";

/// Generic device struct found from sysfs
#[derive(Clone, Debug)]
pub(crate) struct SysDevice {
    pub(crate) name: OsString,
}

/// Finds all the devices in sysfs for a given class sorted by name
pub(crate) fn find_devices_by_class(class: String) -> Result<Vec<SysDevice>> {
    let devices_path = Path::new(SYS_CLASS_DIR).join(class);
    let mut found_devices: Vec<SysDevice> = vec![];
    if !devices_path.exists() {
        // Nothing to do since no devices detected
        return Ok(found_devices);
    }

    let sys_devices_dirs = fs::read_dir(devices_path).context(error::InfinibandSysDevicesSnafu)?;
    for device in sys_devices_dirs {
        let device = device.context(error::InfinibandDeviceSnafu)?;
        let device_name: OsString = device.file_name();
        found_devices.push(SysDevice { name: device_name })
    }

    found_devices.sort_by_key(|device| device.name.clone());
    Ok(found_devices)
}

/// Returns true if the SW_MNG_VALUE is found in the Vital Product Data file for given sysfs device
pub(crate) fn is_device_sw_mng(device: OsString) -> Result<bool> {
    let vpd_file = Path::new(SYS_CLASS_DIR)
        .join(SW_MNG_CLASS)
        .join(device)
        .join("device")
        .join("vpd");
    if vpd_file.exists() {
        let vpd_file_bytes: &[u8] =
            &std::fs::read(vpd_file.as_path()).context(error::ReadFileSnafu {
                path: vpd_file.as_path(),
            })?;
        let needle = SW_MNG_VALUE.as_bytes();
        if vpd_file_bytes
            .windows(needle.len())
            .any(|window| window == needle)
        {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Struct that holds the two important values for an Infiniband Port when checking for
/// Subnet Management capabilties.
#[derive(Clone, Debug)]
pub(crate) struct InfinibandPort {
    /// Capability Mask is read in as a string such as 0xa751e848
    pub(crate) capability_mask: CapabilityMask,
    /// Port GUID is a u64 that is read in as a : formated string but written out in a form such as 0x
    pub(crate) port_guid: Guid,
}

impl InfinibandPort {
    /// is_sm_enabled checks the specific capability bit for Subnet Management means its enabled
    // The actual bit means `isSMDisabled`, so check if its not zero
    pub(crate) fn is_sm_enabled(&self) -> bool {
        let bit_position: u32 = 10;
        let mask: u32 = 1 << bit_position;
        if !(&self.capability_mask & mask) != 0 {
            return true;
        }
        false
    }
}

// Given a device in sysfs, iterate over the known paths where ports are defined
// Iterate over the ports and read in the capability mask and Port GUID for each port
pub(crate) fn find_ports_for_device(device: OsString) -> Result<Vec<InfinibandPort>> {
    let mut found_ports: Vec<InfinibandPort> = vec![];
    let ports_path = Path::new(SYS_CLASS_DIR)
        .join(SW_MNG_CLASS)
        .join(device)
        .join("ports");

    let port_directories = fs::read_dir(ports_path).context(error::InfinibandSysDevicesSnafu)?;
    for port in port_directories {
        let mut capability_mask: String = "".to_string();
        let mut first_guid: String = "".to_string();

        let port = port.context(error::InfinibandSysDevicesSnafu)?;
        let capability_mask_path = port.path().join("cap_mask");
        if capability_mask_path.exists() {
            capability_mask = std::fs::read_to_string(capability_mask_path.as_path()).context(
                error::ReadFileSnafu {
                    path: capability_mask_path.as_path(),
                },
            )?;
        }
        let first_guid_path = port.path().join("gids").join("0");
        if first_guid_path.exists() {
            first_guid = std::fs::read_to_string(first_guid_path.as_path()).context(
                error::ReadFileSnafu {
                    path: first_guid_path.as_path(),
                },
            )?;
        }
        // If a capability mask and port guid have been read, create the Infiniband Port
        if !capability_mask.is_empty() && !first_guid.is_empty() {
            found_ports.push(InfinibandPort {
                capability_mask: CapabilityMask::from_str(capability_mask.as_str())?,
                port_guid: Guid::from_str(first_guid.as_str())?,
            });
        }
    }
    Ok(found_ports)
}

/// Guid struct to help with custom FromStr and ToString
#[derive(Clone, Debug)]
pub(crate) struct Guid(String);

impl FromStr for Guid {
    type Err = error::Error;
    /// String is expected to look like "fe80:0000:0000:0000:e09d:7303:003f:3bf8"
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        let potential_guid = s.trim().to_string();
        ensure!(
            potential_guid.starts_with("fe80"),
            error::InvalidGuidStringSnafu {
                guid: potential_guid
            }
        );

        let guid = Guid(s.trim().to_string());
        Ok(guid)
    }
}

impl ToString for Guid {
    /// From the docs on usage around this GUID:
    /// A U64 bit number queried from the CX device to allow FM to communicate with underlying NVSwitches.
    /// We use this to trim down the second half of the value which is the required part for this functionality
    ///
    /// example "fe80:0000:0000:0000:e09d:7303:003f:3bf8" -> "0xe09d7303003f3bf8"
    fn to_string(&self) -> String {
        let full_string = self.0.to_string();
        let parts: Vec<&str> = full_string.split(":").collect();
        if parts.len() == 8 {
            return format!("0x{}{}{}{}", parts[4], parts[5], parts[6], parts[7]);
        }
        self.0.to_string()
    }
}

/// Capability Mask struct to help with FromStr and bit masking
#[derive(Clone, Debug)]
pub(crate) struct CapabilityMask(u32);

impl FromStr for CapabilityMask {
    type Err = error::Error;
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        let mask = hex_string_to_u32(s.trim()).context(error::CapabilityCheckSnafu { mask: s })?;
        Ok(CapabilityMask(mask))
    }
}

impl BitAnd<u32> for CapabilityMask {
    type Output = u32;

    fn bitand(self, rhs: u32) -> Self::Output {
        self.0 & rhs
    }
}

impl BitAnd<u32> for &CapabilityMask {
    type Output = u32;

    fn bitand(self, rhs: u32) -> Self::Output {
        self.0 & rhs
    }
}

// Helper function to take the string Capability mask and convert to u32
fn hex_string_to_u32(hex: &str) -> std::result::Result<u32, std::num::ParseIntError> {
    let hex_str = hex.strip_prefix("0x").unwrap_or(hex);
    u32::from_str_radix(hex_str, 16)
}
