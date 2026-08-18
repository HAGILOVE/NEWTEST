/**
 * Regulatory / service band reference.
 * Used to snap the design frequency, annotate charts and warn about EIRP caps.
 * Limits are the common headline values - always confirm against the current
 * national regulation before certification.
 */
export const BANDS = [
  { id: 'lora433', name: 'ISM 433 MHz (EU)', f0: 433.92e6, lo: 433.05e6, hi: 434.79e6, region: 'EU', eirpDbm: 10, note: 'SRD band, 10 % duty cycle' },
  { id: 'sub868', name: 'SRD 868 MHz (EU)', f0: 868e6, lo: 863e6, hi: 870e6, region: 'EU', eirpDbm: 14, note: 'LoRa/Sigfox, duty-cycle limited' },
  { id: 'sub915', name: 'ISM 915 MHz (US)', f0: 915e6, lo: 902e6, hi: 928e6, region: 'US', eirpDbm: 36, note: 'FHSS or DSSS, 1 W conducted max' },
  { id: 'gps', name: 'GPS L1 / GNSS', f0: 1575.42e6, lo: 1559e6, hi: 1610e6, region: 'Global', eirpDbm: null, note: 'RHCP receive only' },
  { id: 'gpsL5', name: 'GNSS L5 / E5a', f0: 1176.45e6, lo: 1164e6, hi: 1189e6, region: 'Global', eirpDbm: null, note: 'RHCP, wide correlation bandwidth' },
  { id: 'lte1800', name: 'LTE band 3 (1.8 GHz)', f0: 1.8e9, lo: 1.71e9, hi: 1.88e9, region: 'Global', eirpDbm: null, note: 'FDD cellular' },
  { id: 'n78', name: '5G NR n78 (3.5 GHz)', f0: 3.5e9, lo: 3.3e9, hi: 3.8e9, region: 'Global', eirpDbm: null, note: 'TDD mid-band, massive MIMO' },
  { id: 'n79', name: '5G NR n79 (4.7 GHz)', f0: 4.7e9, lo: 4.4e9, hi: 5.0e9, region: 'APAC', eirpDbm: null, note: 'TDD' },
  { id: 'wifi24', name: 'Wi-Fi 2.4 GHz / BLE', f0: 2.442e9, lo: 2.400e9, hi: 2.4835e9, region: 'Global', eirpDbm: 20, note: '100 mW EIRP in EU, 36 dBm point-to-point in US' },
  { id: 'wifi5', name: 'Wi-Fi 5 GHz (U-NII)', f0: 5.5e9, lo: 5.15e9, hi: 5.875e9, region: 'Global', eirpDbm: 23, note: 'DFS required on U-NII-2' },
  { id: 'wifi6e', name: 'Wi-Fi 6E/7 (6 GHz)', f0: 6.5e9, lo: 5.925e9, hi: 7.125e9, region: 'US/EU', eirpDbm: 23, note: 'LPI indoor / VLP portable classes' },
  { id: 'uwb', name: 'UWB channel 5/9', f0: 6.8e9, lo: 6.24e9, hi: 8.24e9, region: 'Global', eirpDbm: -41.3, note: '-41.3 dBm/MHz PSD limit' },
  { id: 'x', name: 'X-band radar / satcom', f0: 9.5e9, lo: 8.0e9, hi: 12.0e9, region: 'Global', eirpDbm: null, note: 'Marine radar, downlink' },
  { id: 'ku', name: 'Ku-band VSAT', f0: 12.5e9, lo: 10.7e9, hi: 14.5e9, region: 'Global', eirpDbm: null, note: 'Rain fade is the dominant link term' },
  { id: 'k24', name: 'ISM 24 GHz radar', f0: 24.125e9, lo: 24.0e9, hi: 24.25e9, region: 'Global', eirpDbm: 20, note: 'Narrowband ISM; 24.05-24.25 SRR being phased out' },
  { id: 'n257', name: '5G FR2 n257 (28 GHz)', f0: 28e9, lo: 26.5e9, hi: 29.5e9, region: 'Global', eirpDbm: 43, note: 'Phased array, EIRP-limited' },
  { id: 'n260', name: '5G FR2 n260 (39 GHz)', f0: 39e9, lo: 37e9, hi: 40e9, region: 'US', eirpDbm: 43, note: 'Phased array' },
  { id: 'v60', name: '60 GHz unlicensed (WiGig)', f0: 60e9, lo: 57e9, hi: 71e9, region: 'Global', eirpDbm: 40, note: 'Oxygen absorption ~15 dB/km - short range by physics' },
  { id: 'w77', name: '77 GHz automotive radar', f0: 77e9, lo: 76e9, hi: 81e9, region: 'Global', eirpDbm: 55, note: '76-77 long range, 77-81 short range wideband' },
  { id: 'w94', name: '94 GHz imaging', f0: 94e9, lo: 92e9, hi: 96e9, region: 'Research', eirpDbm: null, note: 'Atmospheric window for imaging radiometry' },
  { id: 'd140', name: 'D-band (140 GHz)', f0: 140e9, lo: 130e9, hi: 150e9, region: 'Research', eirpDbm: null, note: '6G candidate backhaul band' },
];

export const BAND_BY_ID = Object.fromEntries(BANDS.map((b) => [b.id, b]));

/** Which band contains a frequency (first match). */
export function bandFor(f) {
  return BANDS.find((b) => f >= b.lo && f <= b.hi) || null;
}

/** Required fractional bandwidth to cover a whole band, centred. */
export function bandFractional(b) {
  const fc = (b.lo + b.hi) / 2;
  return (b.hi - b.lo) / fc;
}
