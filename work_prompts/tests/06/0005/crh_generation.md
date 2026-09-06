# 0005 — crh_generation.txt

> réparation JSON : JSON réparé : 1 fermeture(s) excédentaire(s) (']' ou '}') retirée(s) en fin de fichier

Nouvel Hôpital Civil - Hôpitaux Universitaires de Strasbourg
Service de Cancérologie Adulte

Compte rendu d'hospitalisation

Nom : Reyjasse
Prénom : Sylvestre
Date de naissance : 04/08/1970

### Motif d'hospitalisation
M. Sylvestre Reyjasse, âgé de 55 ans, est hospitalisé ce jour pour la mise en place d'une chimiothérapie dans le cadre d'un adénocarcinome pancréatique localement avancé avec métastases hépatiques synchrones.

### Antécédents
- Médicaux : Pas d'antécédent notable.
- Chirurgicaux : Aucun.
- Familiaux : Non contributifs.
- Allergies : Aucune connue.

### Mode de vie
Le patient ne fume pas et ne consomme pas d'alcool. Il mesure 184 cm pour un poids de 82 kg (IMC à 24,2). Il exerce une activité professionnelle sédentaire.

### Histoire de la maladie
M. Reyjasse a présenté il y a trois semaines un ictère cutanéo-muqueux associé à des douleurs épigastriques irradiant dans le dos. Une échographie abdominale réalisée en ville a révélé une masse pancréatique corporéo-caudale avec dilatation des voies biliaires intra-hépatiques. Le bilan d'extension par TDM thoraco-abdomino-pelvien a confirmé la présence d'une lésion tumorale pancréatique localement avancée, envahissant les vaisseaux mésentériques, ainsi que des lésions secondaires hépatiques multiples. Une ponction-biopsie sous écho-endoscopie a permis de poser le diagnostic d'adénocarcinome excréto-canalaire pancréatique. Le dosage du CA 19-9 était élevé à 1250 UI/ml. Le dossier a été discuté en réunion de concertation pluridisciplinaire (RCP), et une chimiothérapie par protocole FOLFIRINOX a été décidée.

### Examen clinique
À l'entrée, le patient est apyrétique, avec une tension artérielle à 130/80 mmHg et une fréquence cardiaque à 78 battements par minute. L'examen abdominal retrouve une sensibilité modérée de l'épigastre sans défense ni masse palpable. Il n'y a pas d'ascite clinique. Le poids est stable à 82 kg. L'état général est conservé (indice de performance OMS à 1).

### Examens complémentaires
- Bilan biologique : Hémoglobine à 12,8 g/dl, leucocytes à 7,2 G/l, plaquettes à 280 G/l. Bilan hépatique perturbé avec bilirubine totale à 32 µmol/l, ALAT à 85 UI/l, ASAT à 78 UI/l, PAL à 210 UI/l, et gamma-GT à 180 UI/l. Créatinine à 78 µmol/l. CA 19-9 contrôlé à 1320 UI/ml.
- Échographie abdominale de contrôle : Confirmation des lésions hépatiques secondaires déjà identifiées, sans modification notable par rapport au bilan initial.

### Conclusion
M. Reyjasse présente un adénocarcinome pancréatique corporéo-caudal localement avancé avec métastases hépatiques synchrones. Une première cure de chimiothérapie par FOLFIRINOX a été administrée ce jour sans complication immédiate. Le patient est autorisé à regagner son domicile avec un rendez-vous de contrôle prévu dans 15 jours pour évaluation de la tolérance et de l'efficacité du traitement. Une nouvelle RCP est programmée après 4 cures pour réévaluer la stratégie thérapeutique.

Strasbourg, le 06/05/2026

Dr Alain Godessa
Cancérologie Adulte


---

## Formulations

```json
{
  "diagnostics": {
    "Tumeur maligne du pancréas endocrine, autre et non précisée (C254+8)": [
      "adénocarcinome pancréatique localement avancé",
      "adénocarcinome excréto-canalaire pancréatique",
      "lésion tumorale pancréatique localement avancée",
      "adénocarcinome pancréatique corporéo-caudal"
    ],
    "Tumeur maligne secondaire du foie et des voies biliaires intrahépatiques (C787)": [
      "métastases hépatiques synchrones",
      "lésions secondaires hépatiques",
      "lésions hépatiques secondaires"
    ]
  },
  "informations": {
    "Date entrée": [
      "06/05/2026"
    ],
    "Date de sortie": [
      "06/05/2026"
    ],
    "Service d'hospitalisation": [
      "Service de Cancérologie Adulte"
    ],
    "Nom/Prénom du médecin": [
      "Dr Alain Godessa"
    ],
    "Nom/Prénom du patient": [
      "Reyjasse Sylvestre"
    ],
    "Poids": [
      "82 kg"
    ],
    "Âge": [
      "55 ans"
    ],
    "Sexe": [
      "Masculin"
    ],
    "État général": [
      "état général est conservé (indice de performance OMS à 1)"
    ],
    "NFS": [
      "Hémoglobine à 12,8 g/dl, leucocytes à 7,2 G/l, plaquettes à 280 G/l"
    ],
    "Créatinine": [
      "Créatinine à 78 µmol/l"
    ],
    "Bilan hepatique": [
      "bilirubine totale à 32 µmol/l, ALAT à 85 UI/l, ASAT à 78 UI/l, PAL à 210 UI/l, et gamma-GT à 180 UI/l"
    ],
    "Traitements": [
      "chimiothérapie par protocole FOLFIRINOX"
    ]
  }
}
```
