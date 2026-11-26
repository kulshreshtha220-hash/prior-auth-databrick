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

/** Fully documented lung biopsy: every criterion a reviewer looks for is stated explicitly. */
export const STRONG_LUNG_BIOPSY: PriorAuthRequest = {
  patient_name: "Robert Miller",
  patient_dob: "1956-09-04",
  provider_npi: "1720180003",
  diagnosis_codes: ["R91.1", "R05.9", "Z87.891"],
  procedure_codes: ["31628"],
  insurance_id: "MCR-472910385A",
  clinical_notes:
    "REASON FOR REQUEST: Bronchoscopy with transbronchial lung biopsy, single lobe (CPT 31628), for tissue " +
    "diagnosis of an enlarging, PET-avid right lower lobe pulmonary nodule suspicious for primary lung cancer.\n\n" +
    "HISTORY OF PRESENT ILLNESS: 70-year-old male, former smoker (45 pack-years, quit 2019), with a persistent " +
    "dry cough for 4 months. Chest CT 07/10/2026 showed a 1.3 cm solid spiculated RLL nodule. Repeat CT " +
    "10/09/2026 shows growth to 1.9 cm (volume doubling time about 90 days). PET/CT 10/20/2026: nodule FDG-avid, " +
    "SUV max 5.1; no nodal or distant uptake. Brock model malignancy risk 58%. Meets Fleischner Society and " +
    "ACCP criteria for tissue sampling (solid nodule > 8 mm, growth, high pretest probability).\n\n" +
    "PRIOR TREATMENT: 10-day course of amoxicillin-clavulanate (07/2026) and 4 weeks of observation with no " +
    "change in symptoms; interval growth on CT excludes an inflammatory process.\n\n" +
    "SEVERITY AND FUNCTION: Persistent cough disturbing sleep, 4 kg unintentional weight loss over 3 months, " +
    "ECOG performance status 1.\n\n" +
    "PAST MEDICAL HISTORY: Mild COPD (GOLD 1), hypertension, type 2 diabetes (HbA1c 6.8%). Medications: " +
    "tiotropium, amlodipine 5 mg, metformin 1000 mg BID. No anticoagulants or antiplatelet agents. " +
    "Allergies: none known.\n\n" +
    "PRE-PROCEDURE ASSESSMENT: PFTs 10/22/2026: FEV1 74% predicted, DLCO 69% predicted. Labs 10/22/2026: " +
    "platelets 238 K/uL, INR 1.0, creatinine 0.9 mg/dL. ASA class II; acceptable candidate for moderate " +
    "sedation bronchoscopy.\n\n" +
    "PLAN AND RATIONALE: Case reviewed at the multidisciplinary thoracic tumor board 10/24/2026; consensus " +
    "recommendation is bronchoscopic transbronchial biopsy for diagnosis before any surgical resection or " +
    "stereotactic radiation. Bronchoscopic route preferred over CT-guided transthoracic biopsy because of " +
    "emphysema near the pleura (higher pneumothorax risk). Result will determine treatment (lobectomy vs SBRT) " +
    "and staging. Risks (pneumothorax, bleeding, infection) and alternatives discussed; written informed " +
    "consent obtained 10/24/2026.",
};

/** EBUS mediastinal staging for suspected lung cancer with PET-avid nodes. */
export const EBUS_STAGING: PriorAuthRequest = {
  patient_name: "Linda Carter",
  patient_dob: "1961-02-17",
  provider_npi: "1720180003",
  diagnosis_codes: ["R59.0", "R91.8", "Z87.891"],
  procedure_codes: ["31652"],
  insurance_id: "MCR-639204718C",
  clinical_notes:
    "REASON FOR REQUEST: Endobronchial ultrasound with transbronchial needle aspiration of 1-2 mediastinal " +
    "lymph node stations (CPT 31652) for diagnosis and staging of suspected non-small cell lung cancer.\n\n" +
    "HISTORY: 65-year-old female, former smoker (35 pack-years, quit 2021), with 3 months of cough and 3 kg " +
    "weight loss. Chest CT 09/30/2026: 2.6 cm left upper lobe mass with enlarged subcarinal (station 7, 1.8 cm " +
    "short axis) and right lower paratracheal (station 4R, 1.4 cm) lymph nodes. PET/CT 10/14/2026: LUL mass " +
    "SUV max 9.2; stations 7 and 4R FDG-avid (SUV 6.1 and 4.8); no distant disease. Brain MRI 10/16/2026 " +
    "negative.\n\n" +
    "GUIDELINE BASIS: NCCN and ACCP guidelines recommend invasive mediastinal staging, preferably EBUS-TBNA, " +
    "for suspected lung cancer with enlarged or PET-positive mediastinal nodes, before any treatment " +
    "decision. Sampling the nodes gives diagnosis and stage in one minimally invasive procedure; " +
    "contralateral 4R involvement would make the disease N3 (stage IIIB) and change treatment from surgery to " +
    "chemoradiation.\n\n" +
    "PAST MEDICAL HISTORY: Hypothyroidism, osteoarthritis. Medications: levothyroxine 75 mcg. Not on " +
    "anticoagulants. Allergies: penicillin (rash).\n\n" +
    "PRE-PROCEDURE ASSESSMENT: PFTs 10/15/2026 FEV1 81% predicted. Labs 10/15/2026: platelets 265 K/uL, " +
    "INR 1.0. ECOG 0. ASA II.\n\n" +
    "PLAN: Reviewed at multidisciplinary thoracic tumor board 10/17/2026; EBUS-TBNA of stations 7 and 4R " +
    "recommended as the first diagnostic and staging step. Risks and alternatives (mediastinoscopy) discussed; " +
    "informed consent obtained.",
};

export interface SampleCase {
  id: string;
  group: "Score range" | "Approve cases" | "Gate checks";
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
    label: "Highest score: fully documented lung biopsy",
    expected: "APPROVE · HIGH (~0.90+)",
    tone: "success",
    description: "Growth on serial CT, PET-avid, tumor board, failed antibiotics, PFTs, labs, consent: every criterion stated.",
    request: STRONG_LUNG_BIOPSY,
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
    id: "approve-ebus",
    group: "Approve cases",
    label: "Approve: EBUS lung cancer staging",
    expected: "APPROVE · HIGH",
    tone: "success",
    description: "PET-avid mediastinal nodes, guideline-backed staging, tumor board, consent. Different procedure (CPT 31652).",
    request: EBUS_STAGING,
  },
  {
    id: "approve-microsoft",
    group: "Approve cases",
    label: "Approve: Microsoft original sample",
    expected: "APPROVE · HIGH (~0.90)",
    tone: "success",
    description: "The accelerator's own sample case (John Smith, CPT 31628). Approved 0.90 in our notebook test.",
    request: SAMPLE_REQUEST,
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
