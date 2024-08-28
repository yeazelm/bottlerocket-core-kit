/*!
ghostdog is a tool to manage ephemeral disks.
It can be called as a udev helper program to identify ephemeral disks.
*/

use argh::FromArgs;
use gptman::GPT;
use hex_literal::hex;
use lazy_static::lazy_static;
use serde::Deserialize;
use signpost::uuid_to_guid;
use snafu::{ensure, ResultExt};
use std::collections::HashSet;
use std::env;
use std::fs;
use std::io::{Read, Seek};
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::str::FromStr;

const NVME_CLI_PATH: &str = "/sbin/nvme";
const NVME_IDENTIFY_DATA_SIZE: usize = 4096;
const NVIDIA_VENDOR_ID: &str = "0x10de";
const NVIDIA_RUN_DIR: &str = "/run/nvidia";
const DEFAULT_DRIVER_CONFIG_PATH: &str = "/etc/drivers/";
const DRIVER_FACTORY_DIR: &str = "/usr/share/factory/etc/drivers/";
const OPEN_GPU_SUPPORTED_DEVICES_PATH: &str = "/usr/share/nvidia/open-gpu-supported-devices.json";

#[derive(FromArgs, PartialEq, Debug)]
/// Manage ephemeral disks.
struct Args {
    #[argh(subcommand)]
    subcommand: SubCommand,
}

#[derive(FromArgs, PartialEq, Debug)]
#[argh(subcommand)]
enum SubCommand {
    Scan(ScanArgs),
    EbsDeviceName(EbsDeviceNameArgs),
    MatchNvidiaDriver(MatchNvidiaDriverArgs),
}

#[derive(FromArgs, PartialEq, Debug)]
#[argh(subcommand, name = "scan")]
/// Scan a device to see if it is an ephemeral disk.
struct ScanArgs {
    #[argh(positional)]
    device: PathBuf,
}

#[derive(FromArgs, PartialEq, Debug)]
#[argh(subcommand, name = "ebs-device-name")]
/// Returns the device name used for the EBS device
struct EbsDeviceNameArgs {
    #[argh(positional)]
    device: PathBuf,
}

#[derive(FromArgs, PartialEq, Debug)]
#[argh(subcommand, name = "match-nvidia-driver")]
/// Returns the device name used for the EBS device
struct MatchNvidiaDriverArgs {
    #[argh(positional)]
    vendor: String,
}

#[derive(Deserialize)]
#[serde()]
/// Open GPU struct for comparing PCI ID's to a known list of supported devices.
enum SupportedDevicesConfiguration {
    #[serde(rename = "open-gpu")]
    OpenGpu(Vec<GpuDeviceData>),
}

#[derive(PartialEq, Debug, Deserialize)]
/// The GPU Device Data contains various features of the device. Only Name, Device ID, and Features are required
/// a particular device
struct GpuDeviceData {
    #[serde(rename = "devid")]
    /// PCI Device ID
    device_id: String,
    #[serde(rename = "subdevid")]
    /// PCI Subdevice ID
    subdevice_id: Option<String>,
    #[serde(rename = "subvendorid")]
    /// PCI Subvendor ID
    subvendor_id: Option<String>,
    /// Name of the device
    name: String,
    /// List of features the device supports. Noteably we are looking for "kernelopen" to match the driver
    features: Vec<String>,
}

#[derive(Debug, PartialEq, Deserialize)]
/// Struct to hold the PCI_ID which is typically provided as "VENDOR_ID:DEVICE_ID" via udev
struct PciDevice {
    /// PCI Vendor ID
    vendor_id: String,
    /// PCI Device ID
    device_id: String,
}

impl FromStr for PciDevice {
    type Err = String;
    /// The string provided by udev is in the form of "VENDOR_ID:DEVICE_ID" and is parsed as such
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        let mut parts = s.split(':');
        let vendor_id = parts
            .next()
            .map(ToString::to_string)
            .ok_or_else(|| "Mising PCI ID".to_string())?;
        let device_id = parts
            .next()
            .map(ToString::to_string)
            .and_then(|s| (!s.is_empty()).then_some(s))
            .ok_or_else(|| "Missing Device ID".to_string())?;
        if parts.next().is_some() {
            return Err(format!("Invalid PCI_ID provided: {}", s));
        };
        Ok(Self {
            vendor_id,
            device_id,
        })
    }
}

// Main entry point.
fn run() -> Result<()> {
    let args: Args = argh::from_env();
    match args.subcommand {
        SubCommand::Scan(scan_args) => {
            let path = scan_args.device;
            let mut f = fs::File::open(&path).context(error::DeviceOpenSnafu { path })?;
            let device_type = find_device_type(&mut f)?;
            emit_device_type(&device_type);
        }
        SubCommand::EbsDeviceName(ebs_device_name) => {
            let path = ebs_device_name.device;
            let device_name = find_device_name(format!("{}", path.display()))?;
            emit_device_name(&device_name);
        }
        SubCommand::MatchNvidiaDriver(vendor) => {
            // Currently, we only want to run this for NVIDIA devices
            if vendor.vendor == NVIDIA_VENDOR_ID {
                let pci_id = env::var("PCI_ID").context(error::MissingPciIdEnvSnafu)?;
                let driver_choice = find_preferred_driver(pci_id)?;
                // After choosing the driver, drop a marker file provide this decision to others on the system (like systemd)
                if !Path::new(NVIDIA_RUN_DIR).exists() {
                    fs::create_dir_all(NVIDIA_RUN_DIR).context(error::CreateDirSnafu {
                        path: NVIDIA_RUN_DIR,
                    })?;
                }
                let marker_path: PathBuf = Path::new(NVIDIA_RUN_DIR).join(driver_choice.clone());
                fs::write(marker_path.clone(), "").context(error::WriteMarkerFileSnafu {
                    path: marker_path.clone(),
                })?;

                // Copy the driverdog configuration from the factory into /etc/drivers so the preferred driver is loaded
                if !Path::new(DEFAULT_DRIVER_CONFIG_PATH).exists() {
                    fs::create_dir_all(DEFAULT_DRIVER_CONFIG_PATH).context(
                        error::CreateDirSnafu {
                            path: DEFAULT_DRIVER_CONFIG_PATH,
                        },
                    )?;
                }
                let source_driver_path =
                    Path::new(DRIVER_FACTORY_DIR).join(format!("{}.toml", driver_choice.clone()));
                let etc_driver_path = Path::new(DEFAULT_DRIVER_CONFIG_PATH)
                    .join(format!("{}.toml", driver_choice.clone()));
                fs::copy(source_driver_path.clone(), etc_driver_path.clone()).context(
                    error::CopyFileSnafu {
                        s: source_driver_path,
                        d: etc_driver_path,
                    },
                )?;
                // emit the preference back to udev for additional processing in the rule
                println!("BOTTLEROCKET_NVIDIA_DRIVER={}", driver_choice);
            }
        }
    }
    Ok(())
}

/// Find the device type by examining the partition table, if present.
fn find_device_type<R>(reader: &mut R) -> Result<String>
where
    R: Read + Seek,
{
    // We expect the udev rules to only match block disk devices, so it's fair
    // to assume it could have a partition table, and that it's probably an
    // unformatted ephemeral disk if it doesn't.
    let mut device_type = "ephemeral";

    // System disks will either have a known partition type or a partition name
    // that starts with BOTTLEROCKET.
    if let Ok(gpt) = GPT::find_from(reader) {
        let system_device = gpt.iter().any(|(_, p)| {
            p.is_used()
                && (SYSTEM_PARTITION_TYPES.contains(&p.partition_type_guid)
                    || p.partition_name.as_str().starts_with("BOTTLEROCKET"))
        });
        if system_device {
            device_type = "system"
        }
    }

    Ok(device_type.to_string())
}

/// Finds the device name using the nvme-cli
fn find_device_name(path: String) -> Result<String> {
    // nvme-cli writes the binary data to STDOUT
    let output = Command::new(NVME_CLI_PATH)
        .args(["id-ctrl", &path, "-b"])
        .output()
        .context(error::NvmeCommandSnafu { path: path.clone() })?;

    parse_device_name(&output.stdout, path)
}

/// Parses the device name from the binary data returned by nvme-cli
fn parse_device_name(device_info: &[u8], path: String) -> Result<String> {
    // Bail out if the data returned isn't complete
    ensure!(
        device_info.len() == NVME_IDENTIFY_DATA_SIZE,
        error::InvalidDeviceInfoSnafu { path }
    );

    // The vendor data is stored at the last 1024 bytes
    // The device name is stored at the first 32 bytes of the vendor data
    let offset = NVME_IDENTIFY_DATA_SIZE - 1024;
    let device_name = &device_info[offset..offset + 32];

    // Remove `/dev` in case the returned device name includes it, the udev
    // rule already includes that prefix
    Ok(String::from_utf8_lossy(device_name)
        .trim_start_matches("/dev/")
        .trim_end()
        .to_string())
}

/// Read a file into a SupportedDevicesConfiguration Enum
fn read_supported_devices_file(path: PathBuf) -> Result<SupportedDevicesConfiguration> {
    let mut supported_devices_file =
        fs::File::open(&path).context(error::OpenFileSnafu { path: path.clone() })?;
    let mut supported_devices_str = String::new();
    supported_devices_file
        .read_to_string(&mut supported_devices_str)
        .context(error::ReadFileSnafu { path: path.clone() })?;
    let device_configuration: SupportedDevicesConfiguration =
        serde_json::from_str(supported_devices_str.as_str())
            .context(error::ParseGpuDevicesFileSnafu {})?;
    Ok(device_configuration)
}

/// Given a PCI ID, search the Open GPU Supported Devices File to determine if the Open GPU Driver should be used
fn find_preferred_driver(pci_id: String) -> Result<String> {
    // This corresponds to T4 devices which are Turing based and supported, but currently do not show up in the supported-devices file
    if pci_id == "10DE:1EB8" {
        return Ok("nvidia-open-gpu".to_string());
    }
    let open_gpu_devices = read_supported_devices_file(OPEN_GPU_SUPPORTED_DEVICES_PATH.into())?;
    let input_device =
        PciDevice::from_str(pci_id.as_str()).map_err(|message| error::Error::ParsePciId {
            pci_id: pci_id.clone(),
            message,
        })?;
    match open_gpu_devices {
        SupportedDevicesConfiguration::OpenGpu(device_list) => {
            for supported_device in device_list.iter() {
                if supported_device.device_id == input_device.device_id {
                    return Ok("nvidia-open-gpu".to_string());
                }
            }
        }
    }

    // If we don't find a match, choose the proprietary driver
    Ok("nvidia-tesla".to_string())
}

/// Print the device type in the environment key format udev expects.
fn emit_device_type(device_type: &str) {
    println!("BOTTLEROCKET_DEVICE_TYPE={}", device_type);
}

/// Print the device name in the environment key format udev expects.
fn emit_device_name(device_name: &str) {
    println!("XVD_DEVICE_NAME={}", device_name)
}

// Known system partition types for Bottlerocket.
lazy_static! {
    static ref SYSTEM_PARTITION_TYPES: HashSet<[u8; 16]> = [
        uuid_to_guid(hex!("c12a7328 f81f 11d2 ba4b 00a0c93ec93b")), // EFI_SYSTEM
        uuid_to_guid(hex!("6b636168 7420 6568 2070 6c616e657421")), // BOTTLEROCKET_BOOT
        uuid_to_guid(hex!("5526016a 1a97 4ea4 b39a b7c8c6ca4502")), // BOTTLEROCKET_ROOT
        uuid_to_guid(hex!("598f10af c955 4456 6a99 7720068a6cea")), // BOTTLEROCKET_HASH
        uuid_to_guid(hex!("0c5d99a5 d331 4147 baef 08e2b855bdc9")), // BOTTLEROCKET_RESERVED
        uuid_to_guid(hex!("440408bb eb0b 4328 a6e5 a29038fad706")), // BOTTLEROCKET_PRIVATE
        uuid_to_guid(hex!("626f7474 6c65 6474 6861 726d61726b73")), // BOTTLEROCKET_DATA
    ].iter().copied().collect();
}

// Returning a Result from main makes it print a Debug representation of the error, but with Snafu
// we have nice Display representations of the error, so we wrap "main" (run) and print any error.
// https://github.com/shepmaster/snafu/issues/110
fn main() {
    if let Err(e) = run() {
        eprintln!("{}", e);
        std::process::exit(1);
    }
}

/// Potential errors during `ghostdog` execution.
mod error {

    use snafu::Snafu;
    #[derive(Debug, Snafu)]
    #[snafu(visibility(pub(super)))]

    pub(super) enum Error {
        #[snafu(display("Failed to open '{}': {}", path.display(), source))]
        DeviceOpen {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Failed to execute NVMe command for device '{}': {}", path.display(), source))]
        NvmeCommand {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Invalid device info for device '{}'", path.display()))]
        InvalidDeviceInfo { path: std::path::PathBuf },
        #[snafu(display("No ENV variable for PCI_ID provided"))]
        MissingPciIdEnv { source: std::env::VarError },
        #[snafu(display("Failed to open '{}': {}", path.display(), source))]
        OpenFile {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Failed to read '{}': {}", path.display(), source))]
        ReadFile {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Couldn't parse the GPU Devices File: {}", source))]
        ParseGpuDevicesFile { source: serde_json::Error },
        #[snafu(display("Unable to read PCI_ID provided: `{}`: {}", pci_id, message))]
        ParsePciId { pci_id: String, message: String },
        #[snafu(display("Failed to write '{}': {}", path.display(), source))]
        WriteMarkerFile {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Failed to make directory '{}': {}", path.display(), source))]
        CreateDir {
            path: std::path::PathBuf,
            source: std::io::Error,
        },
        #[snafu(display("Failed to copy '{}' to '{}': {}", s.display(), d.display(), source))]
        CopyFile {
            s: std::path::PathBuf,
            d: std::path::PathBuf,
            source: std::io::Error,
        },
    }
}

type Result<T> = std::result::Result<T, error::Error>;

#[cfg(test)]
mod test {
    use super::*;

    use gptman::{GPTPartitionEntry, GPT};
    use signpost::uuid_to_guid;
    use std::io::Cursor;

    fn test_data() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/tests")
    }

    fn gpt_data(partition_type: [u8; 16], partition_name: &str) -> Vec<u8> {
        let mut data = vec![0; 21 * 512 * 2048];
        let mut cursor = Cursor::new(&mut data);
        let mut gpt = GPT::new_from(&mut cursor, 512, [0xff; 16]).unwrap();
        gpt[1] = GPTPartitionEntry {
            partition_name: partition_name.into(),
            partition_type_guid: partition_type,
            unique_partition_guid: [0xff; 16],
            starting_lba: gpt.header.first_usable_lba,
            ending_lba: gpt.header.last_usable_lba,
            attribute_bits: 0,
        };
        gpt.write_into(&mut cursor).unwrap();
        cursor.into_inner().to_vec()
    }

    #[test]
    fn empty_disk() {
        let data = vec![0; 21 * 512 * 2048];
        assert_eq!(
            find_device_type(&mut Cursor::new(&data)).unwrap(),
            "ephemeral"
        );
    }

    #[test]
    fn partitioned_disk_with_unknown_type() {
        let partition_type = uuid_to_guid(hex!("00000000 0000 0000 0000 000000000000"));
        let partition_name = "";
        let data = gpt_data(partition_type, partition_name);
        assert_eq!(
            find_device_type(&mut Cursor::new(&data)).unwrap(),
            "ephemeral"
        );
    }

    #[test]
    fn partitioned_disk_with_system_type() {
        let partition_type = uuid_to_guid(hex!("440408bb eb0b 4328 a6e5 a29038fad706"));
        let partition_name = "";
        let data = gpt_data(partition_type, partition_name);
        assert_eq!(find_device_type(&mut Cursor::new(&data)).unwrap(), "system");
    }

    #[test]
    fn partitioned_disk_with_system_name() {
        let partition_type = uuid_to_guid(hex!("11111111 1111 1111 1111 111111111111"));
        let partition_name = "BOTTLEROCKET-STUFF";
        let data = gpt_data(partition_type, partition_name);
        assert_eq!(find_device_type(&mut Cursor::new(&data)).unwrap(), "system");
    }

    #[test]
    fn test_valid_device_info() {
        for device_name in ["xvdcz", "/dev/xvdcz"] {
            let device_info = build_device_info(device_name);
            assert_eq!(
                parse_device_name(&device_info, "".to_string()).unwrap(),
                "xvdcz".to_string()
            );
        }
    }

    fn build_device_info(device_name: &str) -> Vec<u8> {
        let mut device_name = device_name.as_bytes().to_vec();
        let mut device_info: Vec<u8> = vec![0; NVME_IDENTIFY_DATA_SIZE - 1024];
        let mut padding = vec![32; NVME_IDENTIFY_DATA_SIZE - device_info.len() - device_name.len()];
        device_info.append(&mut device_name);
        device_info.append(&mut padding);

        device_info
    }

    #[test]
    fn parse_open_gpu_supported_devices_file() {
        let test_json = test_data().join("open-gpu-supported-devices-test.json");

        let test_data = read_supported_devices_file(test_json).unwrap();

        match test_data {
            SupportedDevicesConfiguration::OpenGpu(data) => {
                assert!(data.len() == 5);
            }
        }
    }

    #[test]
    fn parse_pci_id() {
        let good_pci_ids = vec![
            (
                "10DE:1EB8",
                PciDevice {
                    vendor_id: "10DE".to_string(),
                    device_id: "1EB8".to_string(),
                },
            ),
            (
                "10DE:2237",
                PciDevice {
                    vendor_id: "10DE".to_string(),
                    device_id: "2237".to_string(),
                },
            ),
            (
                "10DE:20B0",
                PciDevice {
                    vendor_id: "10DE".to_string(),
                    device_id: "20B0".to_string(),
                },
            ),
            (
                "AB12:CD34",
                PciDevice {
                    vendor_id: "AB12".to_string(),
                    device_id: "CD34".to_string(),
                },
            ),
        ];

        let bad_pci_ids = vec!["10DE", "1234:5678:90AC", "!", "1023432:", "10DE:"];
        for (pci_id, pci_device) in good_pci_ids.into_iter() {
            println!("{}", pci_id);
            let res = PciDevice::from_str(pci_id);
            // assert!(res.is_ok());
            println!("{:?}", &res);
            let device = res.unwrap();
            assert_eq!(device, pci_device);
        }

        for pci_id in bad_pci_ids.iter() {
            let res = PciDevice::from_str(pci_id);
            println!("{}", pci_id);
            assert!(res.is_err());
        }
    }
}
