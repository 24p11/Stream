# 0011 — crh_generation.txt

### Hôpital Rangueil - Centre hospitalier universitaire de Toulouse
**Service de Médecine Interne**

**Compte rendu d'hospitalisation**

**Patient :**
- Nom : Clemot
- Prénom : Yolande
- Date de naissance : 10/05/1962
- Âge : 63 ans

**Dates d'hospitalisation :**
- Entrée : 22/01/2026
- Sortie : 22/01/2026

---

### Motif d’hospitalisation
Mme Yolande Clemot, âgée de 63 ans, a été admise en hospitalisation ambulatoire ce jour pour exploration et prise en charge d’une anémie leuco-érythroblastique associée à une asthénie marquée. Cette patiente, suivie pour une schizophrénie paranoïde évoluant sur un mode continu, présente également une cirrhose hépatique d’étiologie indéterminée, actuellement stable mais nécessitant une évaluation complémentaire.

---

### Antécédents
- **Médicaux :**
  - Schizophrénie paranoïde continue, diagnostiquée il y a une vingtaine d’années, sous traitement antipsychotique au long cours.
  - Cirrhose hépatique mixte, sans étiologie alcoolique ou virale identifiée, connue depuis 5 ans.
  - Obésité modérée (IMC à 34,4 kg/m²).
- **Chirurgicaux :** Appendicectomie dans l’enfance.
- **Familiaux :** Pas d’antécédent notable de maladie hématologique ou hépatique.
- **Allergies :** Aucune allergie médicamenteuse connue.

---

### Mode de vie
Mme Clemot ne fume pas et ne consomme pas d’alcool. Elle vit seule à domicile et bénéficie d’un suivi psychiatrique régulier. Son activité physique est limitée en raison de son asthénie. Elle n’exerce actuellement aucune activité professionnelle.

---

### Histoire de la maladie
La patiente rapporte une asthénie progressive depuis environ 3 mois, associée à une dyspnée d’effort modérée. Elle a consulté son médecin traitant il y a 15 jours, qui a mis en évidence une anémie leuco-érythroblastique sur un hémogramme réalisé en ville (hémoglobine à 9,2 g/dL, présence de précurseurs granuleux et érythroblastes circulants). Devant ce tableau, une hospitalisation ambulatoire a été décidée pour bilan étiologique et prise en charge adaptée.

Par ailleurs, la patiente est suivie depuis plusieurs années pour une cirrhose hépatique cryptogénique, sans épisode de décompensation récente. Son traitement actuel comprend un antipsychotique atypique pour sa schizophrénie, ainsi qu’un bêta-bloquant en prévention primaire des complications de l’hypertension portale.

---

### Examen clinique
À l’admission, la patiente est apyrétique, avec une tension artérielle à 130/80 mmHg et une fréquence cardiaque à 78 battements par minute. Elle pèse 87 kg pour une taille de 159 cm (IMC à 34,4 kg/m²). L’examen cutané ne révèle pas d’ictère ni de pétéchies. On note une discrète pâleur conjonctivale. L’abdomen est souple, sans hépatomégalie ni splénomégalie palpable. Les aires ganglionnaires sont libres. L’examen neurologique est sans particularité en dehors d’une discrète lenteur psychomotrice, compatible avec son traitement antipsychotique.

---

### Examens complémentaires
Un bilan biologique a été réalisé en urgence ce jour :
- **Hémogramme :** Hémoglobine à 9,1 g/dL (normocytaire, normochrome), leucocytes à 5,2 G/L avec présence de myélocytes et métamyélocytes, plaquettes à 180 G/L. Confirmation d’une leuco-érythroblastose.
- **Bilan martial :** Ferritine à 250 µg/L (normale), coefficient de saturation de la transferrine à 30 %.
- **Bilan hépatique :** ASAT à 45 UI/L, ALAT à 38 UI/L, bilirubine totale à 12 µmol/L, albuminémie à 38 g/L, TP à 75 %. Pas de signe d’insuffisance hépatocellulaire aiguë.
- **Électrophorèse des protéines sériques :** Pas de pic monoclonal, hypoalbuminémie modérée.
- **Sérologies virales :** Négatives pour les hépatites B et C.
- **Échographie abdominale :** Foie de taille normale, sans nodule suspect, rate modérément augmentée de volume (14 cm), pas d’ascite.

---

### Conclusion
Mme Clemot présente une anémie leuco-érythroblastique d’étiologie à préciser, dans un contexte de cirrhose hépatique cryptogénique et de schizophrénie paranoïde stable. Les examens réalisés ce jour n’ont pas permis d’identifier une cause évidente à cette anémie, qui pourrait être secondaire à une myélopathie infiltrative ou à une pathologie inflammatoire sous-jacente. Un myélogramme est programmé en ambulatoire pour compléter le bilan.

La patiente regagne son domicile ce jour avec un rendez-vous de suivi en hématologie dans 15 jours. Son traitement actuel est maintenu, et une supplémentation martiale empirique est initiée en attendant les résultats du myélogramme.

**Dr Stephen Boufedji**
Médecine Interne
Hôpital Rangueil - CHU de Toulouse


---

## Formulations

```json
{
  "diagnostics": {
    "Autres anémies précisées (D64.8)": [
      "anémie leuco-érythroblastique",
      "leuco-érythroblastose"
    ],
    "Schizophrénie paranoïde - continue (F20.00)": [
      "schizophrénie paranoïde évoluant sur un mode continu",
      "schizophrénie paranoïde continue"
    ],
    "Cirrhoses du foie, autres et sans précision (K74.6)": [
      "cirrhose hépatique d’étiologie indéterminée",
      "cirrhose hépatique mixte",
      "cirrhose hépatique cryptogénique"
    ],
    "Obésité due à un excès calorique de l'adulte avec indice de masse corporelle [IMC] égal ou supérieur à 30 kg/m² et inférieur à 35 kg/m² (E66.04)": [
      "obésité modérée (IMC à 34,4 kg/m²)"
    ]
  },
  "informations": {
    "Date entrée": [
      "22/01/2026"
    ],
    "Date de sortie": [
      "22/01/2026"
    ],
    "Service d'hospitalisation": [
      "Médecine Interne"
    ],
    "Nom/Prénom du médecin": [
      "Dr Stephen Boufedji"
    ],
    "Nom/Prénom du patient": [
      "Clemot Yolande"
    ],
    "Poids": [
      "87 kg"
    ],
    "Âge": [
      "63 ans"
    ],
    "Sexe": [
      "Féminin"
    ],
    "État général": [
      "asthénie marquée",
      "discrète lenteur psychomotrice"
    ],
    "NFS": [
      "Hémoglobine à 9,1 g/dL (normocytaire, normochrome)",
      "leucocytes à 5,2 G/L avec présence de myélocytes et métamyélocytes",
      "plaquettes à 180 G/L"
    ],
    "Créatinine": [],
    "Bilan hépatique": [
      "ASAT à 45 UI/L",
      "ALAT à 38 UI/L",
      "bilirubine totale à 12 µmol/L",
      "albuminémie à 38 g/L",
      "TP à 75 %"
    ],
    "Traitements": [
      "antipsychotique atypique",
      "bêta-bloquant",
      "supplémentation martiale empirique"
    ]
  }
}
```
