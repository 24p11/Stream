# 0001 — crh_generation.txt

> réparation JSON : JSON réparé : 1 fermeture(s) excédentaire(s) (']' ou '}') retirée(s) en fin de fichier

### Hôpital Larrey - Centre hospitalier universitaire de Toulouse
Service de NEURO-CHIRURGIE

Nom : Grebert
Prénom : Yolande
Date de naissance : 06/07/1969

### Motif d’hospitalisation
Patiente de 56 ans adressée pour une séance de radiothérapie externe dans le cadre de la prise en charge d’un carcinome épidermoïde du col utérin, en association avec une chimiothérapie concomitante. Hospitalisation programmée pour la réalisation du traitement par irradiation avec modulation d’intensité et contrôle de position par imagerie (IGRT).

### Antécédents
- Médicaux : Aucun antécédent notable.
- Chirurgicaux : Appendicectomie dans l’enfance.
- Familiaux : Pas d’antécédent familial de cancer gynécologique connu.
- Allergies : Aucune allergie médicamenteuse connue.

### Mode de vie
Patiente non fumeuse, sans consommation d’alcool. Exerce la profession d’enseignante en école primaire. Vit seule à domicile, autonome. Deux grossesses menées à terme, pas d’antécédent de contraception hormonale prolongée.

### Histoire de la maladie
Diagnostic initial posé en janvier 2026 devant des métrorragies post-ménopausiques. Une biopsie cervicale a confirmé la présence d’un carcinome épidermoïde bien différencié du col utérin. Le bilan d’extension réalisé par IRM pelvienne et TDM thoraco-abdomino-pelvienne a révélé une tumeur localement avancée, classée cT2bN0M0 selon la classification FIGO 2018. Les marqueurs tumoraux (SCC et CA 125) étaient initialement élevés, avec des valeurs respectives de 8,2 ng/mL et 45 U/mL.

La patiente a bénéficié d’une première ligne de traitement par chimiothérapie néoadjuvante associant cisplatine et paclitaxel, administrée en 3 cycles de 21 jours entre février et mars 2026. La tolérance a été satisfaisante, avec une neutropénie grade 2 transitoire au premier cycle, sans complication infectieuse. Une réévaluation par IRM pelvienne après la chimiothérapie a montré une réduction partielle de la masse tumorale, avec un taux de SCC passant à 3,1 ng/mL. La décision d’une radio-chimiothérapie concomitante a été retenue en réunion de concertation pluridisciplinaire.

### Examen clinique
À l’entrée, la patiente est apyrétique, avec une tension artérielle à 125/75 mmHg et une fréquence cardiaque à 78 battements par minute. Le poids est stable à 61 kg, pour une taille de 1,65 m (IMC à 22,4 kg/m²). L’examen général ne retrouve pas de signe de dénutrition ni d’altération de l’état général (score ECOG à 1). L’examen gynécologique sous spéculum met en évidence une lésion ulcéro-infiltrante du col utérin, sans extension vaginale visible. Les aires ganglionnaires sont libres, sans adénopathie palpable. L’examen abdominal est sans particularité, sans hépatomégalie ni masse palpable.

### Examens complémentaires
- **Bilan biologique** : Hémoglobine à 12,1 g/dL, leucocytes à 5 800/mm³ (neutrophiles à 3 200/mm³), plaquettes à 245 000/mm³. Fonction rénale normale (créatinine à 72 µmol/L, clairance MDRD à 85 mL/min). Bilan hépatique sans anomalie (ASAT à 22 UI/L, ALAT à 19 UI/L, bilirubine totale à 10 µmol/L). Marqueurs tumoraux : SCC à 2,8 ng/mL, CA 125 à 32 U/mL.
- **Imagerie** : Pas d’imagerie réalisée pendant cette hospitalisation, les examens de référence datant de la semaine précédente étant considérés comme valides pour la planification du traitement.

### Évolution pendant l'hospitalisation
La patiente a bénéficié d’une séance d’irradiation externe par modulation d’intensité (IGRT) ciblant la tumeur cervicale et les aires ganglionnaires pelviennes, sans complication immédiate. La tolérance a été bonne, avec une discrète asthénie post-radiothérapie, sans signe de toxicité cutanée ou digestive. La chimiothérapie concomitante par cisplatine (40 mg/m²) a été administrée en ambulatoire le jour même, avec une hydratation préventive et une surveillance rapprochée de la diurèse et de la fonction rénale. La patiente a regagné son domicile le lendemain, avec une ordonnance de traitement symptomatique (antiemétiques, antalgiques de palier 1) et un rendez-vous de suivi programmé dans 3 semaines pour évaluation de la tolérance et poursuite du protocole.

### Conclusion
Patiente de 56 ans présentant un carcinome épidermoïde du col utérin localement avancé (cT2bN0M0), en cours de traitement par radio-chimiothérapie concomitante. Hospitalisation pour séance d’irradiation externe avec modulation d’intensité, bien tolérée. Poursuite du protocole selon les modalités prévues, avec surveillance clinique et biologique rapprochée.

Dr Dorota Artigue
Service de Neuro-Chirurgie
Hôpital Larrey - CHU de Toulouse


---

## Formulations

```json
{
  "diagnostics": {
    "Tumeur maligne du col de l'utérus, sans précision (C539)": [
      "carcinome épidermoïde du col utérin",
      "carcinome épidermoïde bien différencié du col utérin",
      "lésion ulcéro-infiltrante du col utérin"
    ],
    "Séance de chimiothérapie pour tumeur (Z511)": [
      "chimiothérapie concomitante",
      "chimiothérapie néoadjuvante associant cisplatine et paclitaxel",
      "chimiothérapie concomitante par cisplatine"
    ]
  },
  "informations": {
    "Date entrée": [
      "06/03/2026"
    ],
    "Date de sortie": [
      "07/03/2026"
    ],
    "Service d'hospitalisation": [
      "Service de NEURO-CHIRURGIE"
    ],
    "Nom/Prénom du médecin": [
      "Dr Dorota Artigue"
    ],
    "Nom/Prénom du patient": [
      "Grebert Yolande"
    ],
    "Âge": [
      "56 ans"
    ],
    "Sexe": [
      "Féminin"
    ],
    "État général": [
      "score ECOG à 1"
    ],
    "Poids": [
      "61 kg"
    ],
    "Statut gestationnel": [],
    "Gestité": [
      "Deux grossesses menées à terme"
    ],
    "Topographie de la tumeur primaire": [
      "col de l’utérus"
    ],
    "Histologie tumorale": [
      "carcinome épidermoïde bien différencié"
    ],
    "Stade tumoral": [
      "cT2bN0M0",
      "tumeur localement avancée"
    ],
    "Biomarqueurs tumoraux": [
      "SCC à 2,8 ng/mL",
      "CA 125 à 32 U/mL",
      "SCC et CA 125"
    ],
    "Sites métastatiques": [],
    "Évolutivité tumorale": [
      "réduction partielle de la masse tumorale"
    ],
    "Examens pour diagnostic initial": [
      "biopsie cervicale"
    ],
    "Examens d'évaluation du stade tumoral": [
      "IRM pelvienne",
      "TDM thoraco-abdomino-pelvienne"
    ],
    "Examens d’évaluation de l’évolutivité tumorale": [
      "IRM pelvienne"
    ],
    "Traitements antitumoraux": [
      "chimiothérapie néoadjuvante",
      "radio-chimiothérapie concomitante",
      "irradiation externe par modulation d’intensité"
    ],
    "Lignes de traitement antitumoral": [
      "première ligne de traitement"
    ],
    "Médicaments antitumoraux": [
      "cisplatine",
      "paclitaxel"
    ],
    "Cycles de chimiothérapie": [
      "3 cycles de 21 jours"
    ],
    "NFS": [
      "Hémoglobine à 12,1 g/dL",
      "leucocytes à 5 800/mm³ (neutrophiles à 3 200/mm³)",
      "plaquettes à 245 000/mm³"
    ],
    "Créatinine": [
      "créatinine à 72 µmol/L",
      "clairance MDRD à 85 mL/min"
    ],
    "Bilan hepatique": [
      "ASAT à 22 UI/L",
      "ALAT à 19 UI/L",
      "bilirubine totale à 10 µmol/L"
    ]
  }
}
```
