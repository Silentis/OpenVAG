import asyncio
import json
import math
import time
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

from studio.paths import BACKUP_DIR, LOG_DIR

BRAND_MODULES = {
    "vag_2013": [
        {"addr": "01", "name": "Engine"},
        {"addr": "02", "name": "Auto Trans"},
        {"addr": "03", "name": "ABS Brakes"},
        {"addr": "08", "name": "Auto HVAC"},
        {"addr": "09", "name": "Cent. Elect."},
        {"addr": "15", "name": "Airbags"},
        {"addr": "17", "name": "Instruments"},
        {"addr": "19", "name": "CAN Gateway"},
        {"addr": "44", "name": "Steering Assist"},
        {"addr": "46", "name": "Central Conv."},
    ],
    "bmw_eseries": [
        {"addr": "12", "name": "DME / DDE (Engine)"},
        {"addr": "32", "name": "EGS (Auto Trans)"},
        {"addr": "44", "name": "DSC / ABS Brakes"},
        {"addr": "A4", "name": "MRS (Airbags)"},
        {"addr": "80", "name": "KOMBI (Instruments)"},
        {"addr": "5B", "name": "IHKA (Climate)"},
        {"addr": "00", "name": "CAS / EWS (Immobilizer)"},
    ],
    "volvo_p2_p3": [
        {"addr": "7A", "name": "ECM (Engine)"},
        {"addr": "6E", "name": "TCM (Transmission)"},
        {"addr": "01", "name": "BCM (Brake / ABS)"},
        {"addr": "40", "name": "CEM (Central Electronic)"},
        {"addr": "51", "name": "DIM (Driver Info / Cluster)"},
        {"addr": "58", "name": "SRS (Airbags)"},
    ],
    "uds_modern": [
        {"addr": "01", "name": "Engine (UDS)"},
        {"addr": "03", "name": "ABS / ESP (UDS)"},
        {"addr": "17", "name": "Instruments (UDS)"},
        {"addr": "19", "name": "CAN Gateway (UDS)"},
    ],
}


class DiagnosticBridge:
    """Unified Multi-Brand Bridge: VAG (PyVCDS) + BMW + Volvo + Universal OBD-II + UDS."""
    
    def scan_usb_devices(self) -> List[Dict[str, Any]]:
        try:
            ps_cmd = (
                "Get-PnpDevice -PresentOnly | "
                "Where-Object { $_.InstanceId -match 'USB' -and ($_.FriendlyName -match 'USB|Serial|COM|FTDI|Ross|OBD|VAG|CH340|CAN') } | "
                "Select-Object Status,Class,FriendlyName,InstanceId | ConvertTo-Json"
            )
            raw = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                text=True,
                timeout=6,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            ).strip()
            if not raw:
                return []
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else [parsed]
            for it in items:
                self._emit_trace(
                    "SYS", "USB-SCAN",
                    str(it.get("InstanceId", "")),
                    f"{it.get('FriendlyName', '')} [{it.get('Status', '')}]",
                )
            return items
        except Exception as e:
            self._emit_trace("SYS", "USB-ERR", "--", str(e))
            return []
        
    def __init__(self):
        self.connected: bool = False
        self.adapter: str = "mock"
        self.profile: str = "vag_2013"
        self.interface: str = "COM3"
        self.vin: str = ""
        self.active_module: Optional[str] = None
        self.trace_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self.session_logs: List[Dict[str, Any]] = []
        self._t0 = time.time()
        self._obd_conn = None

        self._mock_db = {
            "obd2_universal": {
                "vin": "YV1BW714091000123",
                "ecus": {
                    "7E0": {
                        "part_number": "GENERIC-ECM",
                        "component": "OBD-II Engine Control Module (ISO 15765-4 CAN)",
                        "coding": "N/A (OBD-II Standard)",
                        "wsc": "OBD2",
                        "adaptations": {},
                        "readiness": {
                            "MIL": "OFF", "Misfire": "Ready", "Fuel System": "Ready",
                            "Catalyst": "Ready", "EGR / VVT": "Ready", "DPF / PM Filter": "Not Ready",
                        },
                        "dtcs": [
                            {"code": "P2002", "vag_code": "OBD-II", "desc": "DPF Efficiency Below Threshold", "status": "Pending"},
                        ],
                    }
                },
            },
            "vag_2013": {
                "vin": "WVWZZZ1KZ7W000001",
                "ecus": {
                    "01": {"part_number": "03G 906 021 AN", "component": "R4 1,9L EDC G000SG 9248 (TP2.0)", "coding": "0000071", "wsc": "01279",
                           "adaptations": {"01": "32768", "03": "32768", "06": "1"},
                           "dtcs": [{"code": "P0299", "vag_code": "16683", "desc": "Boost Pressure Regulation: Control Range Not Reached", "status": "Intermittent"}]},
                    "03": {"part_number": "1K0 907 379 AC", "component": "ESP FRONT MK60 0101", "coding": "0021122", "wsc": "01279", "adaptations": {"60": "0"}, "dtcs": []},
                    "09": {"part_number": "3C0 937 049 AJ", "component": "Bordnetz-SG H54 2202", "coding": "E1888F0700041A00470A00000F00000000095D435C0001", "wsc": "01279",
                           "adaptations": {"01": "30", "02": "10", "31": "3"},
                           "dtcs": [{"code": "00978", "vag_code": "00978", "desc": "Lamp for Low Beam; Left (M29)", "status": "Active/Static"}]},
                    "17": {"part_number": "1K0 920 873 B", "component": "KOMBIINSTRUMENT VDD 1612", "coding": "0003103", "wsc": "01279",
                           "adaptations": {"02": "1", "40": "15", "41": "150"}, "dtcs": []},
                    "19": {"part_number": "1K0 907 530 K", "component": "J533 Gateway H12 0170", "coding": "3D3F0740070002", "wsc": "01279", "adaptations": {}, "dtcs": []},
                },
            },
            "bmw_eseries": {
                "vin": "WBAVD11000AV00099",
                "ecus": {
                    "12": {"part_number": "7561834", "component": "DDE 6.0 M57TU2 (D-CAN / KWP2000)", "coding": "Read-Only (BMW)", "wsc": "BMW", "adaptations": {},
                           "dtcs": [{"code": "4530", "vag_code": "BMW-DDE", "desc": "Charge-air pressure control, control deviation", "status": "Present"}]},
                    "44": {"part_number": "6776065", "component": "DSC MK60 E90", "coding": "Read-Only (BMW)", "wsc": "BMW", "adaptations": {}, "dtcs": []},
                    "80": {"part_number": "6979120", "component": "KOMBI E90 High", "coding": "Read-Only (BMW)", "wsc": "BMW", "adaptations": {}, "dtcs": []},
                    "A4": {"part_number": "6977446", "component": "ACSM / MRS5 Airbag", "coding": "Read-Only (BMW)", "wsc": "BMW", "adaptations": {},
                           "dtcs": [{"code": "93B2", "vag_code": "BMW-SRS", "desc": "Safety battery terminal resistance too high", "status": "Stored"}]},
                },
            },
            "volvo_p2_p3": {
                "vin": "YV1SZ595771260001",
                "ecus": {
                    "7A": {"part_number": "30785100", "component": "ECM D5244T4 (29-bit CAN 500kbps)", "coding": "Read-Only (Volvo)", "wsc": "VIDA", "adaptations": {},
                           "dtcs": [{"code": "ECM-1507", "vag_code": "VOLVO", "desc": "Turbo control - Too low pressure", "status": "Active"}]},
                    "40": {"part_number": "30786475", "component": "CEM Central Electronic Module", "coding": "Read-Only (Volvo)", "wsc": "VIDA", "adaptations": {}, "dtcs": []},
                    "01": {"part_number": "30793884", "component": "BCM Brake Control Module", "coding": "Read-Only (Volvo)", "wsc": "VIDA", "adaptations": {}, "dtcs": []},
                    "51": {"part_number": "30746112", "component": "DIM Driver Information Module", "coding": "Read-Only (Volvo)", "wsc": "VIDA", "adaptations": {}, "dtcs": []},
                },
            },
            "uds_modern": {
                "vin": "WAUZZZF40JA000042",
                "ecus": {
                    "01": {"part_number": "04L 906 026 BN", "component": "R4 2.0l TDI H25 3541 (UDS ISO-14229)", "coding": "01250012032401080000", "wsc": "06335", "adaptations": {},
                           "dtcs": [{"code": "P20EE", "vag_code": "UDS:21122", "desc": "SCR NOx Catalyst Efficiency Below Threshold", "status": "Active"}]},
                    "19": {"part_number": "8W0 907 468 F", "component": "J533 Gateway (UDS / SFD Protected)", "coding": "0301000100000000", "wsc": "06335", "adaptations": {}, "dtcs": []},
                },
            },
        }

    def _emit_trace(self, direction: str, proto: str, raw_hex: str, note: str = ""):
        entry = {
            "ts": round(time.time() - self._t0, 3),
            "utc": datetime.utcnow().isoformat(),
            "profile": self.profile,
            "adapter": self.adapter,
            "dir": direction,
            "proto": proto,
            "raw": raw_hex,
            "note": note,
        }
        self.session_logs.append(entry)
        if len(self.session_logs) > 5000:
            self.session_logs.pop(0)
        if self.trace_queue.full():
            try:
                self.trace_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.trace_queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass

    def export_session_log(self) -> Dict[str, Any]:
        ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        vin_safe = self.vin or "NO_VIN"
        filename = f"diag_log_{self.profile}_{vin_safe}_{ts_str}.jsonl"
        path = LOG_DIR / filename
        with open(path, "w", encoding="utf-8") as f:
            header = {"meta": True, "profile": self.profile, "adapter": self.adapter, "interface": self.interface, "vin": self.vin}
            f.write(json.dumps(header) + "\n")
            for row in self.session_logs:
                f.write(json.dumps(row) + "\n")
        return {"filename": filename, "path": str(path), "count": len(self.session_logs)}

    def list_backups(self) -> List[Dict[str, Any]]:
        entries = []
        for p in sorted(BACKUP_DIR.glob("*.jsonl"), reverse=True):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entries.append(json.loads(line))
        return entries[-50:][::-1]

    async def connect(self, adapter: str, profile: str, interface: str) -> Dict[str, Any]:
        self.adapter = adapter
        self.profile = profile
        self.interface = interface
        self.session_logs.clear()

        if adapter == "mock":
            self.connected = True
            self.vin = self._mock_db[profile]["vin"]
            self._emit_trace("SYS", profile.upper(), "00", f"Simulator connected ({interface})")
            return {"connected": True, "profile": profile, "vin": self.vin}

        if adapter == "obdlink_elm" and profile == "obd2_universal":
            import obd
            self._obd_conn = await asyncio.to_thread(obd.OBD, interface)
            if not self._obd_conn.is_connected():
                raise RuntimeError(f"Could not connect to OBD-II adapter on {interface}")
            vin_resp = await asyncio.to_thread(self._obd_conn.query, obd.commands.VIN)
            self.vin = str(vin_resp.value) if vin_resp and not vin_resp.is_null() else "UNKNOWN_VIN"
            self.connected = True
            self._emit_trace("SYS", "OBD2", "ATZ", f"Connected on {interface} | VIN: {self.vin}")
            return {"connected": True, "profile": profile, "vin": self.vin}

        raise NotImplementedError(
            f"Hardware mode '{adapter}' + '{profile}' needs the physical cable trace/test first. Use Simulator or Universal OBD-II with OBDLink/ELM."
        )

    async def disconnect(self):
        if self._obd_conn:
            try:
                await asyncio.to_thread(self._obd_conn.close)
            except Exception:
                pass
            self._obd_conn = None
        self.connected = False
        self.active_module = None
        self._emit_trace("SYS", "DISC", "--", "Disconnected")

    def _real_obd_dtcs(self) -> List[Dict[str, Any]]:
        import obd
        resp = self._obd_conn.query(obd.commands.GET_DTC)
        self._emit_trace("TX", "OBD2", "03", "Mode 03 Read DTCs")
        if not resp or resp.is_null():
            return []
        out = []
        for code, desc in resp.value:
            out.append({"code": str(code), "vag_code": "OBD-II", "desc": str(desc or "Generic/OEM DTC"), "status": "Stored"})
        self._emit_trace("RX", "OBD2", f"{len(out)} DTC(s)", str(out))
        return out

    def _real_obd_readiness(self) -> Dict[str, str]:
        import obd
        resp = self._obd_conn.query(obd.commands.STATUS)
        if not resp or resp.is_null():
            return {}
        st = resp.value
        readiness = {"MIL": "ON" if getattr(st, "MIL", False) else "OFF"}
        for attr in ("misfire_monitoring", "fuel_system_monitoring", "comprehensive_component_monitoring",
                     "catalyst_monitoring", "egr_system_monitoring"):
            obj = getattr(st, attr, None)
            if obj and getattr(obj, "available", False):
                label = attr.replace("_monitoring", "").replace("_", " ").title()
                readiness[label] = "Ready" if getattr(obj, "complete", False) else "Not Ready"
        return readiness

    async def auto_scan(self) -> List[Dict[str, Any]]:
        if not self.connected:
            raise RuntimeError("Not connected")

        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            dtcs = await asyncio.to_thread(self._real_obd_dtcs)
            readiness = await asyncio.to_thread(self._real_obd_readiness)
            return [{
                "addr": "7E0", "name": "OBD-II Engine / Emissions",
                "fault_count": len(dtcs), "part_number": "OBD2-ECU",
                "component": f"Protocol: {self._obd_conn.protocol_name()}",
                "coding": "N/A", "readiness": readiness,
            }]

        results = []
        ecus = self._mock_db[self.profile]["ecus"]

        if self.profile == "obd2_universal":
            self._emit_trace("TX", "OBD2", "7DF 02 01 00", "Query Supported PIDs")
            await asyncio.sleep(0.08)
            ecu = ecus["7E0"]
            return [{
                "addr": "7E0", "name": "OBD-II Engine / Emissions",
                "fault_count": len(ecu["dtcs"]), "part_number": ecu["part_number"],
                "component": ecu["component"], "coding": ecu["coding"], "readiness": ecu.get("readiness"),
            }]

        proto_map = {"vag_2013": "VWTP", "bmw_eseries": "D-CAN/DS2", "volvo_p2_p3": "VOLVO-29BIT", "uds_modern": "UDS"}
        proto_label = proto_map.get(self.profile, "CAN")

        for mod in BRAND_MODULES.get(self.profile, []):
            addr = mod["addr"]
            self._emit_trace("TX", proto_label, f"Scan -> 0x{addr}", mod["name"])
            await asyncio.sleep(0.03)
            if addr in ecus:
                ecu = ecus[addr]
                results.append({
                    "addr": addr, "name": mod["name"], "fault_count": len(ecu["dtcs"]),
                    "part_number": ecu["part_number"], "component": ecu["component"], "coding": ecu["coding"],
                })
        return results

    async def clear_all_dtcs(self) -> Dict[str, Any]:
        if not self.connected:
            raise RuntimeError("Not connected")
        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            await self.clear_dtcs("7E0")
            return {"cleared_modules": 1}

        ecus = self._mock_db[self.profile]["ecus"]
        count = 0
        for addr, ecu in ecus.items():
            if ecu["dtcs"]:
                ecu["dtcs"] = []
                count += 1
                self._emit_trace("TX", self.profile.upper(), f"ClearDTC 0x{addr}", "Global Clear")
        return {"cleared_modules": count}

    async def open_module(self, addr: str) -> Dict[str, Any]:
        self.active_module = addr
        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            dtcs = await asyncio.to_thread(self._real_obd_dtcs)
            readiness = await asyncio.to_thread(self._real_obd_readiness)
            return {
                "addr": addr, "profile": self.profile, "part_number": "OBD2-ECU",
                "component": f"Protocol: {self._obd_conn.protocol_name()}",
                "coding": "N/A", "wsc": "OBD2", "dtcs": dtcs, "readiness": readiness, "adaptations": {},
            }

        ecus = self._mock_db[self.profile]["ecus"]
        if addr not in ecus:
            raise ValueError(f"Module {addr} did not respond")
        self._emit_trace("TX", self.profile.upper(), f"Open 0x{addr}", "Read ECU ID & DTCs")
        return {"addr": addr, "profile": self.profile, **ecus[addr]}

    async def read_dtcs(self, addr: str) -> List[Dict[str, Any]]:
        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            return await asyncio.to_thread(self._real_obd_dtcs)
        return self._mock_db[self.profile]["ecus"][addr]["dtcs"]

    async def clear_dtcs(self, addr: str) -> Dict[str, Any]:
        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            import obd
            self._emit_trace("TX", "OBD2", "04", "Mode 04 Clear DTCs")
            await asyncio.to_thread(self._obd_conn.query, obd.commands.CLEAR_DTC)
            return {"cleared": True}

        self._emit_trace("TX", self.profile.upper(), "ClearDTC (0x04 / 0x14)", f"Module 0x{addr}")
        self._mock_db[self.profile]["ecus"][addr]["dtcs"] = []
        return {"cleared": True}

    async def read_measuring_block(self, addr: str, group: int) -> Dict[str, Any]:
        t = time.time() - self._t0
        if self.adapter == "obdlink_elm" and self.profile == "obd2_universal":
            import obd
            def _poll():
                cmds = [
                    ("Engine RPM", obd.commands.RPM, "rpm"),
                    ("Coolant Temp", obd.commands.COOLANT_TEMP, "°C"),
                    ("Intake MAP", obd.commands.INTAKE_PRESSURE, "kPa"),
                    ("Voltage", obd.commands.CONTROL_MODULE_VOLTAGE, "V"),
                ]
                out = []
                for label, cmd, unit in cmds:
                    r = self._obd_conn.query(cmd)
                    val = round(float(r.value.magnitude), 2) if r and not r.is_null() and hasattr(r.value, "magnitude") else 0
                    out.append({"label": label, "value": val, "unit": unit})
                return out
            cells = await asyncio.to_thread(_poll)
            self._emit_trace("RX", "OBD2-PID", f"grp={group}", str([c["value"] for c in cells]))
            return {"group": group, "ts": round(t, 3), "cells": cells}

        self._emit_trace("TX", self.profile.upper(), f"Read Block/PID {group}", f"Module 0x{addr}")
        if group == 11:
            cells = [
                {"label": "Engine Speed", "value": round(1850 + 350 * math.sin(t * 1.1), 0), "unit": "rpm"},
                {"label": "Spec. Boost", "value": round(1950 + 250 * math.sin(t * 0.8), 0), "unit": "mbar"},
                {"label": "Actual Boost", "value": round(1920 + 240 * math.sin(t * 0.8 - 0.15), 0), "unit": "mbar"},
                {"label": "N75 Duty Cycle", "value": round(52 + 15 * math.sin(t * 0.8), 1), "unit": "%"},
            ]
        elif group == 13:
            cells = [
                {"label": "Cyl 1 Inj. Dev", "value": round(-0.18 + 0.08 * math.sin(t), 2), "unit": "mg/str"},
                {"label": "Cyl 2 Inj. Dev", "value": round(0.12 + 0.06 * math.cos(t), 2), "unit": "mg/str"},
                {"label": "Cyl 3 Inj. Dev", "value": round(-0.05 + 0.05 * math.sin(t * 1.3), 2), "unit": "mg/str"},
                {"label": "Cyl 4 Inj. Dev", "value": round(0.11 + 0.07 * math.cos(t * 1.1), 2), "unit": "mg/str"},
            ]
        else:
            cells = [
                {"label": "Engine Speed", "value": round(840 + 65 * math.sin(t * 1.4), 0), "unit": "rpm"},
                {"label": "Coolant Temp", "value": round(89.0 + 1.1 * math.sin(t * 0.1), 1), "unit": "°C"},
                {"label": "Intake / Boost", "value": round(1025 + 90 * math.sin(t * 0.8), 0), "unit": "mbar"},
                {"label": "Battery Voltage", "value": round(14.1 + 0.1 * math.cos(t * 0.5), 2), "unit": "V"},
            ]
        return {"group": group, "ts": round(t, 3), "cells": cells}

    async def write_coding(self, addr: str, new_coding: str) -> Dict[str, Any]:
        if self.adapter != "mock":
            raise NotImplementedError("Hardware coding write requires verified ECU security session.")
        if self.profile not in ("vag_2013", "uds_modern"):
            raise ValueError(f"Coding writes are disabled on {self.profile} for safety.")
        ecu = self._mock_db[self.profile]["ecus"][addr]
        old_coding = ecu["coding"]
        with open(BACKUP_DIR / f"backup_{self.vin}_{addr}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "vin": self.vin, "addr": addr, "type": "coding", "old": old_coding, "new": new_coding}) + "\n")
        ecu["coding"] = new_coding
        self._emit_trace("TX", self.profile.upper(), f"WriteCoding 0x{addr}", f"{old_coding} -> {new_coding}")
        return {"ok": True, "old": old_coding, "new": new_coding}

    async def read_adaptation(self, addr: str, channel: str) -> Dict[str, Any]:
        if self.adapter != "mock":
            raise NotImplementedError("Adaptation read on real hardware will be enabled per protocol.")
        ecu = self._mock_db[self.profile]["ecus"][addr]
        val = ecu.get("adaptations", {}).get(channel, "0")
        self._emit_trace("TX", self.profile.upper(), f"ReadAdapt 0x{addr} ch={channel}", f"Value={val}")
        return {"channel": channel, "value": val}

    async def write_adaptation(self, addr: str, channel: str, value: str) -> Dict[str, Any]:
        if self.adapter != "mock":
            raise NotImplementedError("Adaptation write on real hardware requires verified ECU support.")
        ecu = self._mock_db[self.profile]["ecus"][addr]
        old_val = ecu.get("adaptations", {}).get(channel, "0")
        with open(BACKUP_DIR / f"backup_{self.vin}_{addr}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.utcnow().isoformat(), "vin": self.vin, "addr": addr, "type": f"adapt_ch_{channel}", "old": old_val, "new": value}) + "\n")
        ecu.setdefault("adaptations", {})[channel] = value
        self._emit_trace("TX", self.profile.upper(), f"WriteAdapt 0x{addr} ch={channel}", f"{old_val} -> {value}")
        return {"ok": True, "channel": channel, "old": old_val, "new": value}

    async def run_output_test(self, addr: str, test_id: str) -> Dict[str, Any]:
        if not self.connected:
            raise RuntimeError("Not connected")
        if self.adapter != "mock":
            raise NotImplementedError("Hardware actuator tests require verified protocol driver.")
        self._emit_trace("TX", self.profile.upper(), f"OutputTest 0x{addr}", f"Trigger={test_id}")
        await asyncio.sleep(0.35)
        self._emit_trace("RX", self.profile.upper(), "71 01", f"Actuator '{test_id}' completed")
        return {"ok": True, "test": test_id, "message": f"Actuator '{test_id}' pulsed & verified on Module {addr}."}

    async def run_service_function(self, action: str) -> Dict[str, Any]:
        if not self.connected:
            raise RuntimeError("Connect to vehicle first.")
        if self.adapter != "mock":
            raise NotImplementedError(f"Service routine '{action}' needs hardware protocol wiring for your adapter.")

        messages = {
            "oil_reset": "Service interval reset on Module 17 (Instruments): Channel 02 set to 0.",
            "epb_open": "Rear EPB calipers retracted (Basic Setting 007). Safe to replace brake pads.",
            "epb_close": "Rear EPB calipers closed and clamped (Basic Setting 006).",
            "dpf_regen": "DPF check: Soot mass 18.4g (Normal). Forced stationary regen routine ready.",
            "bms_reset": "Battery Energy Management updated (Module 19/61): New battery serial registered.",
            "tba_align": "Throttle Body Alignment (Group 060/098) completed — ADP OK.",
            "g85_cal": "Steering Angle Sensor G85 zero-point calibration completed on ABS Module 03.",
        }
        self._emit_trace("TX", self.profile.upper(), f"Service:{action}", "Executing routine")
        await asyncio.sleep(0.3)
        msg = messages.get(action, f"Service routine '{action}' executed.")
        self._emit_trace("RX", self.profile.upper(), "OK", msg)
        return {"ok": True, "action": action, "message": msg}