#### Variable catégorie de séjour selon la typologie ci dessous qui sera ajouté au données du scénario :
* Adultes
    - Séances simples (radiothérapie, dialyse, aphérèse) adultes & pédiatrie
       * Documentation obligatoire : Absence de CRH, DP donné en fonction de critères objectif (médicament, actes)
       * Difficultés codage : aucune
       * Méthode codage auto : règles de décision Médicaments, actes
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification :  Age >= 18,  CMD 28 à l'exclusion des autres types de séances
    - Séance polysomno :
       * Documentation obligatoire : CR d'examen polysomnographique
       * Difficultés codage : faible (choix du DP à partir CRH mais périmètre très limité)
       * Méthode codage auto : étude CRH 
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, CMD 28, DP = Z04801
    - Séance Chimiothérapie simple adulte :
       * Documentation obligatoire : Médicaments, CRH inconstant
       * Difficultés codage : faible, recopie diagnostic séance précédente, difficulté : s'assurer que la chimio bien eu lieu, codage DAS
       * Méthode codage auto : règles de décisions
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, CMD 28, DP = Z511, non première séance      
    - Séance Chimiothérapie/radiothérapie complexe adulte : première séance, fait intercurent, complication
       * Caractétristique : Médicaments, CRH
       * Difficultés codage : faible, choix du DR, choix des DAS
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, CMD 28, DP = Z511, première séance ou complication décelée
    - HDJ Médecine adultes
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS, gradation des soins
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : modérés
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Type hospitalisation = HDJ, Type GHM M ou Z
    - Médecine adultes < 3 Nuits
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : modéré
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Durée < 3, Type GHM M ou Z
    - Interventionnel adultes < 3 Nuits
       * Caractétristique : CR acte +/- CRH
       * Difficultés codage : modérée, choix du DP mais acte, choix DAS
       * Méthode codage auto : étude CR acte +/- CRH + Acte CCAM
       * Impact codage valorisation : modéré
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Durée < 3, Type GHM K
    - Chirurgie adultes < 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire +/- CRH
       * Difficultés codage : modérée, choix du DP mais acte, choix DAS
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM (NER + Classification posible)
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 15,Durée < 3, Type GHM C
    - Médecine adultes > 3 Nuits
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18,, Durée  3, Type GHM M ou Z
    -  Inteventionnel adultes > 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire + CRH
       * Difficultés codage : élevée, choix du DP mais acte, choix DAS
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Durée >3 jours, Type GHM K
    -  Chirurgie adultes > 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire + CRH
       * Difficultés codage : élevée, choix du DP mais acte, choix DAS
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 15, Durée >3 jours, Type GHM C
    - SC adultes
       * Caractétristique : CRH
       * Difficultés codage : très élevée, choix du DP, choix DAS
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Passage authorisation SC
    - Greffes de moelle, Car-T Cells adultes
       * Caractétristique : CRH
       * Difficultés codage : très élevée, histoire longues, complications fréquentes, choix du DP, choix DAS
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : 27Z02, 27Z03 +  Acte Car-T cells
    - Hospitalisation et réanimation brulés adultes
       * Caractétristique : CRH
       * Difficultés codage : très élevée, histoire longues, complications fréquentes, choix du DP, choix DAS
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Autorisation traitement des brûlés
    - Transplantations
       * Caractétristique : CRH
       * Difficultés codage : très élevée, histoire longues, complications fréquentes, choix du DP, choix DAS
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : racine 27C02, 27C03, 27C04, 27C05, 27C06, 27C07 
* Obstrétique
    - IVG 
       * Documentation obligatoire : CRH
       * Difficultés codage : faible
       * Méthode codage auto : règles de décision actes, identification situation
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : GHM 14Z08Z
    - IMG & Fausse couches
       * Documentation obligatoire : CRH + CR Obstétrical
       * Difficultés codage : faible
       * Méthode codage auto : élévé, choix DP et DAS mais règles bien établies
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Racine 14Z04,14C05, 14C06, 14C09, 14Z10, 14Z15,14Z09  
    - Accouchement normal mère
       * Documentation obligatoire : CR Obstétrical + Suites de couches
       * Difficultés codage : faible
       * Méthode codage auto : règles de décision actes, indentification situation
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : GHM 14C07A,14C08A, 14Z10, 14Z11A,14Z12A,14Z13A,14Z13T,14Z14A,14Z14T  
    - Accouchement pathologique mère
       * Documentation obligatoire : CRH + CR Obstétrical + Suites de couches
       * Difficultés codage : élevé
       * Méthode codage auto : Analyse CRH + CR Obstétrical + Suites de couches
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : racine 14C03, racine GHM 14C03,14C07,14C08, 14Z10, 14Z11,14Z12,14Z13,14Z14 + sévérité non A et non T 
* Néonatalogie
    - Bébé normal
       * Documentation obligatoire : Absence de CRH systématique
       * Difficultés codage : faible
       * Méthode codage auto : Actes, données administratives, poids de naissance
       * Impact codage valorisation : faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification :15M05, 15M06, 15M07, 15M08, 15M09, 15M10,15M11, 15M13, 15M14 et sévérité = A et pas de passage en néonat
    - Bébé néonat
       * Documentation obligatoire : CRH
       * Difficultés codage : très élévée, activité technique et spécifique, faibles volumes
       * Méthode codage auto : données administratives, poids de naissance, analyse CRH
       * Impact codage valorisation : très élevé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification :passage en unité de néonatologie
    - SC néonat
       * Documentation obligatoire : CRH
       * Difficultés codage : très élévée, activité technique et spécifique, faibles volumes
       * Méthode codage auto : données administratives, poids de naissance, analyse CRH
       * Impact codage valorisation : très élevé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification :passage en unité SC néonatologie
* Pédiatrie
    - Séance Chimiothérapie simple pédiatrie
       * Documentation obligatoire : Médicaments, CRH inconstant (?)
       * Difficultés codage : faible, recopie diagnostic séance précédente, difficulté : s'assurer que la chimio bien eu lieu, codage DAS
       * Méthode codage auto : règles de décisions
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18, CMD 28, DP = Z511, non première séance 
    - Séance Chimiothérapie complexe pédiatrie : première séance, fait intercurent, complication
       * Caractétristique : Médicaments, CRH
       * Difficultés codage : faible, choix du DR, choix des DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : très faible
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18, CMD 28, DP = Z511, première séance ou complication décelée
        - HDJ Médecine pédiatrie
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS, gradation des soins, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : modérés
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Type hospitalisation = HDJ, Type GHM M ou Z
    - Médecine pédiatrie < 3 Nuits
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : modéré
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Durée < 3, Type GHM M ou Z
    - Interventionnel pédiatrie < 3 Nuits
       * Caractétristique : CR acte +/- CRH
       * Difficultés codage : modérée, choix du DP mais acte, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CR acte +/- CRH + Acte CCAM
       * Impact codage valorisation : modéré
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18, Durée < 3, Type GHM K
    - Chirurgie pédiatrie < 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire +/- CRH
       * Difficultés codage : modérée, choix du DP mais acte, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM (NER + Classification posible)
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 15,Durée < 3, Type GHM C
    - Médecine pédiatrie > 3 Nuits
       * Caractétristique : CRH
       * Difficultés codage : élevée, choix du DP au regard règles, choix DR, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CRH
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18,, Durée  3, Type GHM M ou Z
    -  Inteventionnel pédiatrie > 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire + CRH
       * Difficultés codage : élevée, choix du DP mais acte, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18, Durée >3 jours, Type GHM K
    -  Chirurgie pédiatrie > 3 Nuits
       * Caractétristique : Courrier pré-op + CR opératoire + CRH
       * Difficultés codage : élevée, choix du DP mais acte, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : étude CR opératoire +/- CRH + Acte CCAM
       * Impact codage valorisation : élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 15, Durée >3 jours, Type GHM C
    - SC pédiatrie
       * Caractétristique : CRH
       * Difficultés codage : très élevée, choix du DP, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age >= 18, Passage authorisation SC
    - Greffes de moelle, Car-T Cells pédiatrie
       * Caractétristique : CRH
       * Difficultés codage : très élevée, histoire longues, complications fréquentes, choix du DP, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Acte de greffe
    - Hospitalisation et réanimation brulés pédiatrie
       * Caractétristique : CRH
       * Difficultés codage : très élevée, histoire longues, complications fréquentes, choix du DP, choix DAS, difficulté plus élevée adulte (faibles volumes, PEC parfois très spécifiques)
       * Méthode codage auto : CRH
       * Impact codage valorisation : très élévé
       * Volumétrie :
          - Nb séjours 
          - Recettes
       * Identification : Age < 18, Autorisation traitement des brûlés