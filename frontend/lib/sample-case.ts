import type { PriorAuthRequest } from "./types";

export const SAMPLE_REQUEST: PriorAuthRequest = {
  patient_name: "John Smith",
  patient_dob: "1958-03-15",
  provider_npi: "1720180003",
  diagnosis_codes: ["R91.1", "J18.9", "R05.9"],
  procedure_codes: ["31628"],
  clinical_notes:
    "68-year-old male presenting with persistent right lower lobe pulmonary " +
    "nodule. CT chest (01/15/2026) demonstrates a 1.8 cm spiculated nodule " +
    "in the RLL, increased from 1.2 cm on prior CT (10/12/2025), consistent " +
    "with interval growth over 3 months. PET/CT (01/22/2026) shows FDG " +
    "avidity with SUV max of 4.2, concerning for malignancy.\n\n" +
    "PMH: COPD (mild, GOLD stage I), hypertension, hyperlipidemia. " +
    "40 pack-year smoking history, quit 5 years ago. No prior history of " +
    "malignancy. Family history significant for lung cancer (father, age 72). " +
    "Medications: albuterol inhaler PRN, lisinopril 10 mg daily, " +
    "atorvastatin 20 mg daily. Allergies: NKDA.\n\n" +
    "Physical exam: Vitals BP 132/78, HR 76, RR 16, SpO2 95% on room air. " +
    "Lungs with decreased breath sounds at right base; no wheezing or " +
    "crackles. Remainder of exam unremarkable.\n\n" +
    "Labs (01/20/2026): WBC 9.2 K/uL, Hgb 14.1 g/dL, Platelets 245 K/uL, " +
    "INR 1.0, Creatinine 0.9 mg/dL, BUN 18 mg/dL. Comprehensive metabolic " +
    "panel within normal limits.\n\n" +
    "Pulmonary function tests (01/18/2026): FEV1 78% predicted, FVC 82% " +
    "predicted, FEV1/FVC ratio 0.73, DLCO 71% predicted. Patient is an " +
    "acceptable surgical candidate.\n\n" +
    "Patient completed a 14-day course of amoxicillin-clavulanate with no " +
    "resolution of the nodule. Given the spiculated morphology, interval " +
    "growth, FDG avidity (SUV 4.2), and significant smoking history, there " +
    "is high suspicion for primary lung malignancy per Fleischner Society " +
    "guidelines. Recommend CT-guided transbronchial lung biopsy (CPT 31628) " +
    "for tissue diagnosis. Risks including pneumothorax and bleeding were " +
    "discussed; patient consents to proceed.",
  insurance_id: "MCR-123456789A",
};

export interface SampleCase {
  id: string;
  group: "Score range" | "Gate checks";
  label: string;
  expected: string;
  tone: "success" | "warning" | "danger" | "info";
  description: string;
  request: PriorAuthRequest;
}

/** Demo cases: one per score band plus one per gate, so every outcome can be shown. */
export const SAMPLE_CASES: SampleCase[] = [
  {
    id: "high",
    group: "Score range",
    label: "Highest score: complete lung biopsy case",
    expected: "APPROVE · HIGH (~0.90)",
    tone: "success",
    description: "Microsoft's sample: growing nodule, PET, PFTs, failed antibiotics, consent. Every gate passes.",
    request: SAMPLE_REQUEST,
  },
  {
    id: "medium",
    group: "Score range",
    label: "Middle score: right procedure, partial evidence",
    expected: "PEND · MEDIUM (~0.55–0.75), Gate 3",
    tone: "warning",
    description: "Real lung specialist and valid codes, but no growth comparison, PET, PFTs or prior treatment.",
    request: {
      patient_name: "Maria Lopez",
      patient_dob: "1964-07-22",
      provider_npi: "1720180003",
      diagnosis_codes: ["R91.1"],
      procedure_codes: ["31628"],
      insurance_id: "MCR-884213570B",
      clinical_notes:
        "62-year-old female with a 1.4 cm right upper lobe pulmonary nodule found incidentally on " +
        "chest CT (02/03/2026) done for abdominal pain. Reports mild intermittent cough for about " +
        "two months. Former smoker, quit 10 years ago. No prior chest imaging available for " +
        "comparison. Referred for bronchoscopic transbronchial lung biopsy (CPT 31628) to establish " +
        "a tissue diagnosis.",
    },
  },
  {
    id: "low",
    group: "Score range",
    label: "Lowest score: wrong specialty, thin notes",
    expected: "PEND · LOW (<0.50), Gate 3",
    tone: "danger",
    description: "Lung specialist requests a total knee replacement with a one-line note and no insurance ID.",
    request: {
      patient_name: "Raj Patel",
      patient_dob: "1955-11-02",
      provider_npi: "1720180003",
      diagnosis_codes: ["M17.11"],
      procedure_codes: ["27447"],
      insurance_id: "",
      clinical_notes: "Right knee pain. Wants knee replacement.",
    },
  },
  {
    id: "gate1",
    group: "Gate checks",
    label: "Gate 1 fail: provider NPI not found",
    expected: "PEND · Gate 1 (provider)",
    tone: "info",
    description: "Same complete clinical case, but NPI 1234567890 is not a registered provider.",
    request: { ...SAMPLE_REQUEST, patient_name: "Maria Garcia", provider_npi: "1234567890", insurance_id: "MCR-999000111C" },
  },
  {
    id: "gate2",
    group: "Gate checks",
    label: "Gate 2 fail: invalid diagnosis code",
    expected: "PEND · Gate 2 (codes)",
    tone: "info",
    description: "Same complete clinical case, but ICD-10 R99.99 does not exist.",
    request: { ...SAMPLE_REQUEST, patient_name: "Jane Doe", diagnosis_codes: ["R99.99"], insurance_id: "MCR-555123456D" },
  },
];
