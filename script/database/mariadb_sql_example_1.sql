SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET AUTOCOMMIT = 0;
START TRANSACTION;
SET time_zone = "+00:00";

--
-- Structure de la table `tbl_organization`
--

CREATE TABLE `tbl_organization` (
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NoRegion` int(10) UNSIGNED NOT NULL,
  `NoVille` int(10) UNSIGNED NOT NULL,
  `NoArrondissement` int(10) UNSIGNED DEFAULT NULL,
  `NoCartier` int(10) UNSIGNED DEFAULT NULL,
  `Nom` varchar(45) CHARACTER SET latin1 DEFAULT NULL,
  `NomComplet` varchar(255) COLLATE latin1_general_ci NOT NULL,
  `AdresseOrganization` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `CodePostalOrganization` varchar(7) CHARACTER SET latin1 DEFAULT NULL,
  `TelOrganization` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `TelecopieurOrganization` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `CourrielOrganization` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `MessageGrpAchat` text COLLATE latin1_general_ci,
  `MessageAccueil` text COLLATE latin1_general_ci,
  `URL_Public_Organization` varchar(255) COLLATE latin1_general_ci DEFAULT NULL,
  `URL_Transac_Organization` varchar(255) COLLATE latin1_general_ci DEFAULT NULL,
  `URL_LogoOrganization` varchar(255) COLLATE latin1_general_ci DEFAULT NULL,
  `GrpAchat_Admin` tinyint(4) DEFAULT '0',
  `GrpAchat_Organizateur` tinyint(4) DEFAULT '0',
  `NonVisible` int(11) NOT NULL DEFAULT '0',
  `DateMAJ_Organization` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_achat_ponctuel`
--

CREATE TABLE `tbl_achat_ponctuel` (
  `NoAchatPonctuel` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED NOT NULL,
  `DateAchatPonctuel` date DEFAULT NULL,
  `MontantPaiementAchatPonct` decimal(8,2) DEFAULT '0.00',
  `AchatPoncFacturer` tinyint(3) UNSIGNED DEFAULT '0',
  `TaxeF_AchatPonct` double UNSIGNED DEFAULT '0',
  `TaxeP_AchatPonct` double UNSIGNED DEFAULT '0',
  `Majoration_AchatPonct` double UNSIGNED DEFAULT '0',
  `DateMAJ_AchantPonct` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_achat_ponctuel_produit`
--

CREATE TABLE `tbl_achat_ponctuel_produit` (
  `NoAchatPonctuelProduit` int(10) UNSIGNED NOT NULL,
  `NoAchatPonctuel` int(10) UNSIGNED NOT NULL,
  `NoFournisseurProduit` int(10) UNSIGNED NOT NULL,
  `QteAcheter` double UNSIGNED DEFAULT '0',
  `CoutUnit_AchatPonctProd` decimal(8,2) DEFAULT '0.00',
  `SiTaxableF_AchatPonctProd` tinyint(4) DEFAULT '0',
  `SiTaxableP_AchatPonctProd` tinyint(4) DEFAULT '0',
  `PrixFacturer_AchatPonctProd` decimal(8,2) DEFAULT '0.00',
  `DateMAJ_AchatPoncProduit` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_arrondissement`
--

CREATE TABLE `tbl_arrondissement` (
  `NoArrondissement` int(10) UNSIGNED NOT NULL,
  `NoVille` int(11) DEFAULT NULL,
  `Arrondissement` varchar(60) CHARACTER SET latin1 DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_cartier`
--

CREATE TABLE `tbl_cartier` (
  `NoCartier` int(10) UNSIGNED NOT NULL,
  `NoArrondissement` int(10) UNSIGNED NOT NULL DEFAULT '0',
  `Cartier` varchar(60) CHARACTER SET latin1 DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_categorie`
--

CREATE TABLE `tbl_categorie` (
  `NoCategorie` int(10) UNSIGNED NOT NULL,
  `TitreCategorie` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `Supprimer` int(1) DEFAULT NULL,
  `Approuver` int(1) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_categorie_sous_categorie`
--

CREATE TABLE `tbl_categorie_sous_categorie` (
  `NoCategorieSousCategorie` int(10) UNSIGNED NOT NULL,
  `NoSousCategorie` char(2) CHARACTER SET latin1 DEFAULT NULL,
  `NoCategorie` int(10) UNSIGNED DEFAULT NULL,
  `TitreOffre` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `Supprimer` int(1) DEFAULT NULL,
  `Approuver` int(1) DEFAULT NULL,
  `Description` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `NoOffre` int(10) UNSIGNED DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_commande`
--

CREATE TABLE `tbl_commande` (
  `NoCommande` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED NOT NULL,
  `NoRefCommande` int(10) UNSIGNED DEFAULT '0',
  `DateCmdDebut` date DEFAULT NULL,
  `DateCmdFin` date DEFAULT NULL,
  `DateCueillette` date DEFAULT NULL,
  `TaxePCommande` double UNSIGNED DEFAULT '0',
  `TaxeFCommande` double UNSIGNED DEFAULT '0',
  `Majoration` double UNSIGNED DEFAULT '0',
  `CommandeTermine` tinyint(3) UNSIGNED DEFAULT '0',
  `DateMAJ_Cmd` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_commande_membre`
--

CREATE TABLE `tbl_commande_membre` (
  `NoCommandeMembre` int(10) UNSIGNED NOT NULL,
  `NoCommande` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED NOT NULL,
  `NumRefMembre` int(10) UNSIGNED DEFAULT '0',
  `CmdConfirmer` tinyint(3) UNSIGNED DEFAULT '0',
  `Facturer` tinyint(3) UNSIGNED DEFAULT '0',
  `MontantPaiement` decimal(10,2) DEFAULT '0.00',
  `CoutUnitaireAJour` tinyint(3) UNSIGNED DEFAULT '0',
  `DateCmdMb` datetime DEFAULT NULL,
  `DateFacture` date DEFAULT NULL,
  `ArchiveSousTotal` decimal(10,2) DEFAULT '0.00',
  `ArchiveTotMajoration` decimal(10,2) DEFAULT '0.00',
  `ArchiveTotTxFed` decimal(10,2) DEFAULT '0.00',
  `ArchiveTotTxProv` decimal(10,2) DEFAULT '0.00',
  `DateMAJ_CmdMembre` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_commande_membre_produit`
--

CREATE TABLE `tbl_commande_membre_produit` (
  `NoCmdMbProduit` int(10) UNSIGNED NOT NULL,
  `NoCommandeMembre` int(10) UNSIGNED NOT NULL,
  `NoFournisseurProduitCommande` int(10) UNSIGNED NOT NULL,
  `Qte` double DEFAULT '0',
  `QteDePlus` double DEFAULT '0',
  `Ajustement` double DEFAULT '0',
  `CoutUnitaire_Facture` decimal(5,2) DEFAULT '0.00',
  `SiTaxableP_Facture` tinyint(4) DEFAULT '0',
  `SiTaxableF_Facture` tinyint(4) DEFAULT '0',
  `PrixFacturer_Manuel` decimal(5,2) DEFAULT '0.00',
  `DateMAJ_CmdMembreProd` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_commentaire`
--

CREATE TABLE `tbl_commentaire` (
  `NoCommentaire` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED NOT NULL,
  `NoMembreSource` int(10) UNSIGNED NOT NULL,
  `NoMembreViser` int(10) UNSIGNED DEFAULT NULL,
  `NoOffreServiceMembre` int(10) UNSIGNED DEFAULT NULL,
  `NoDemandeService` int(10) UNSIGNED DEFAULT NULL,
  `DateHeureAjout` datetime DEFAULT NULL,
  `Situation_Impliquant` tinyint(3) UNSIGNED DEFAULT NULL,
  `NomEmployer` varchar(50) COLLATE latin1_general_ci DEFAULT NULL,
  `NomComite` varchar(50) COLLATE latin1_general_ci DEFAULT NULL,
  `AutreSituation` varchar(81) COLLATE latin1_general_ci DEFAULT NULL,
  `SatisfactionInsatisfaction` tinyint(3) UNSIGNED DEFAULT NULL,
  `DateIncident` date DEFAULT NULL,
  `TypeOffre` tinyint(3) UNSIGNED DEFAULT NULL,
  `ResumerSituation` text COLLATE latin1_general_ci,
  `Demarche` text COLLATE latin1_general_ci,
  `SolutionPourRegler` text COLLATE latin1_general_ci,
  `AutreCommentaire` text COLLATE latin1_general_ci,
  `SiConfidentiel` tinyint(3) UNSIGNED DEFAULT NULL,
  `NoteAdministrative` text COLLATE latin1_general_ci,
  `ConsulterOrganization` tinyint(3) UNSIGNED DEFAULT '0',
  `ConsulterReseau` tinyint(3) UNSIGNED DEFAULT '0',
  `DateMaj_Commentaire` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_demande_service`
--

CREATE TABLE `tbl_demande_service` (
  `NoDemandeService` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED DEFAULT NULL,
  `NoOrganization` int(10) UNSIGNED DEFAULT NULL,
  `TitreDemande` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `Description` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `Approuve` int(1) DEFAULT NULL,
  `Supprimer` int(1) DEFAULT NULL,
  `Transmit` int(1) DEFAULT NULL,
  `DateDebut` date DEFAULT NULL,
  `DateFin` date DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_dmd_adhesion`
--

CREATE TABLE `tbl_dmd_adhesion` (
  `NoDmdAdhesion` int(10) UNSIGNED NOT NULL,
  `NoOrganization` int(10) UNSIGNED NOT NULL DEFAULT '0',
  `Nom` varchar(45) CHARACTER SET latin1 DEFAULT NULL,
  `Prenom` varchar(45) CHARACTER SET latin1 DEFAULT NULL,
  `Telephone` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `Poste` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `Courriel` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `Supprimer` smallint(1) DEFAULT '0',
  `Transferer` smallint(1) DEFAULT '0',
  `EnAttente` tinyint(4) DEFAULT '0',
  `DateMAJ` timestamp NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_droits_admin`
--

CREATE TABLE `tbl_droits_admin` (
  `NoMembre` int(10) UNSIGNED NOT NULL DEFAULT '0',
  `GestionProfil` int(1) DEFAULT '0',
  `GestionCatSousCat` int(1) DEFAULT '0',
  `GestionOffre` int(1) DEFAULT '0',
  `GestionOffreMembre` int(1) DEFAULT '0',
  `SaisieEchange` int(1) DEFAULT '0',
  `Validation` int(1) DEFAULT '0',
  `GestionDmd` int(1) DEFAULT '0',
  `GroupeAchat` tinyint(4) DEFAULT '0',
  `ConsulterProfil` tinyint(4) DEFAULT '0',
  `ConsulterEtatCompte` tinyint(4) DEFAULT '0',
  `GestionFichier` tinyint(4) DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_echange_service`
--

CREATE TABLE `tbl_echange_service` (
  `NoEchangeService` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED DEFAULT NULL,
  `NoMembreVendeur` int(10) UNSIGNED DEFAULT NULL,
  `NoMembreAcheteur` int(10) UNSIGNED DEFAULT NULL,
  `NoDemandeService` int(10) UNSIGNED DEFAULT NULL,
  `NoOffreServiceMembre` int(10) UNSIGNED DEFAULT NULL,
  `NbHeure` time DEFAULT NULL,
  `DateEchange` date DEFAULT NULL,
  `TypeEchange` int(1) UNSIGNED DEFAULT NULL,
  `Remarque` varchar(100) DEFAULT NULL,
  `Commentaire` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_fichier`
--

CREATE TABLE `tbl_fichier` (
  `Id_Fichier` int(10) UNSIGNED NOT NULL,
  `Id_TypeFichier` int(10) UNSIGNED NOT NULL,
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NomFichierStokage` varchar(255) COLLATE latin1_general_ci NOT NULL,
  `NomFichierOriginal` varchar(255) COLLATE latin1_general_ci NOT NULL,
  `Si_Admin` tinyint(3) UNSIGNED DEFAULT '1',
  `Si_OrganizationLocalSeulement` tinyint(3) UNSIGNED DEFAULT '1',
  `Si_Disponible` tinyint(3) UNSIGNED DEFAULT '0',
  `DateMAJ_Fichier` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_fournisseur`
--

CREATE TABLE `tbl_fournisseur` (
  `NoFournisseur` int(10) UNSIGNED NOT NULL,
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NoRegion` int(10) UNSIGNED NOT NULL,
  `NoVille` int(10) UNSIGNED NOT NULL,
  `NomFournisseur` varchar(80) CHARACTER SET latin1 DEFAULT NULL,
  `Adresse` varchar(80) CHARACTER SET latin1 DEFAULT NULL,
  `CodePostalFournisseur` varchar(7) CHARACTER SET latin1 DEFAULT NULL,
  `TelFournisseur` varchar(14) CHARACTER SET latin1 DEFAULT NULL,
  `FaxFounisseur` varchar(40) CHARACTER SET latin1 DEFAULT NULL,
  `CourrielFournisseur` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `NomContact` varchar(100) CHARACTER SET latin1 DEFAULT NULL,
  `PosteContact` varchar(8) CHARACTER SET latin1 DEFAULT NULL,
  `CourrielContact` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `NoteFournisseur` text CHARACTER SET latin1,
  `Visible_Fournisseur` tinyint(1) UNSIGNED DEFAULT '1',
  `DateMAJ_Fournisseur` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_fournisseur_produit`
--

CREATE TABLE `tbl_fournisseur_produit` (
  `NoFournisseurProduit` int(10) UNSIGNED NOT NULL,
  `NoFournisseur` int(10) UNSIGNED NOT NULL,
  `NoProduit` int(10) UNSIGNED NOT NULL,
  `CodeProduit` varchar(25) DEFAULT NULL,
  `zQteStokeAcc` int(10) UNSIGNED DEFAULT '0',
  `zCoutUnitaire` decimal(5,2) UNSIGNED DEFAULT '0.00',
  `Visible_FournisseurProduit` tinyint(4) DEFAULT '1',
  `DateMAJ_FournProduit` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_fournisseur_produit_commande`
--

CREATE TABLE `tbl_fournisseur_produit_commande` (
  `NoFournisseurProduitCommande` int(10) UNSIGNED NOT NULL,
  `NoCommande` int(10) UNSIGNED NOT NULL,
  `NoFournisseurProduit` int(10) UNSIGNED NOT NULL,
  `NbBoiteMinFournisseur` tinyint(3) UNSIGNED DEFAULT '0',
  `QteParBoitePrevu` double UNSIGNED DEFAULT '0',
  `CoutUnitPrevu` decimal(7,2) DEFAULT '0.00',
  `Disponible` tinyint(3) UNSIGNED DEFAULT '1',
  `DateMAJ_FournProdCommande` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_fournisseur_produit_pointservice`
--

CREATE TABLE `tbl_fournisseur_produit_pointservice` (
  `NoFournisseurProduitPointservice` int(10) UNSIGNED NOT NULL,
  `NoFournisseurProduit` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED NOT NULL,
  `QteStokeAcc` int(11) DEFAULT '0',
  `CoutUnitaire` decimal(5,2) DEFAULT '0.00',
  `DateMAJ_FournProdPtServ` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_info_logiciel_bd`
--

CREATE TABLE `tbl_info_logiciel_bd` (
  `NoInfoLogicielBD` int(10) UNSIGNED NOT NULL,
  `DerniereVersionLogiciel` int(10) UNSIGNED DEFAULT NULL,
  `MAJOblig` int(1) UNSIGNED DEFAULT NULL,
  `LienWeb` varchar(255) DEFAULT NULL,
  `DateCreation` timestamp NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

--
-- Structure de la table `tbl_log_acces`
--

CREATE TABLE `tbl_log_acces` (
  `Id_log_acces` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED DEFAULT '0',
  `IP_Client_V4` varchar(50) COLLATE latin1_general_ci DEFAULT NULL,
  `Navigateur` varchar(100) COLLATE latin1_general_ci DEFAULT NULL,
  `Statut` varchar(45) COLLATE latin1_general_ci DEFAULT NULL,
  `NomUsagerEssayer` varchar(45) COLLATE latin1_general_ci DEFAULT NULL,
  `Referer` varchar(255) COLLATE latin1_general_ci DEFAULT NULL,
  `Resolution_H` int(11) DEFAULT '0',
  `Resolution_W` int(11) DEFAULT '0',
  `DateHeure_Deconnexion` datetime DEFAULT NULL,
  `DateHeureConnexion` timestamp NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_membre`
--

CREATE TABLE `tbl_membre` (
  `NoMembre` int(10) UNSIGNED NOT NULL,
  `NoCartier` int(10) UNSIGNED DEFAULT '0',
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED DEFAULT NULL,
  `NoTypeCommunication` int(10) UNSIGNED NOT NULL,
  `NoOccupation` int(10) UNSIGNED NOT NULL,
  `NoOrigine` int(10) UNSIGNED NOT NULL,
  `NoSituationMaison` int(10) UNSIGNED NOT NULL,
  `NoProvenance` int(10) UNSIGNED NOT NULL,
  `NoRevenuFamilial` int(10) UNSIGNED NOT NULL,
  `NoArrondissement` int(10) UNSIGNED DEFAULT NULL,
  `NoVille` int(10) UNSIGNED NOT NULL,
  `NoRegion` int(10) UNSIGNED NOT NULL,
  `MembreCA` tinyint(4) DEFAULT '0',
  `PartSocialPaye` tinyint(4) DEFAULT '0',
  `CodePostal` varchar(7) DEFAULT NULL,
  `DateAdhesion` date DEFAULT NULL,
  `Nom` varchar(45) DEFAULT NULL,
  `Prenom` varchar(45) DEFAULT NULL,
  `Adresse` varchar(255) DEFAULT NULL,
  `Telephone1` varchar(10) DEFAULT NULL,
  `PosteTel1` varchar(10) DEFAULT NULL,
  `NoTypeTel1` int(10) UNSIGNED DEFAULT NULL,
  `Telephone2` varchar(10) DEFAULT NULL,
  `PosteTel2` varchar(10) DEFAULT NULL,
  `NoTypeTel2` int(10) UNSIGNED DEFAULT NULL,
  `Telephone3` varchar(10) DEFAULT NULL,
  `PosteTel3` varchar(10) DEFAULT NULL,
  `NoTypeTel3` int(10) UNSIGNED DEFAULT NULL,
  `Courriel` varchar(255) DEFAULT NULL,
  `AchatRegrouper` tinyint(1) DEFAULT NULL,
  `PretActif` tinyint(1) DEFAULT NULL,
  `PretRadier` tinyint(1) DEFAULT NULL,
  `PretPayer` tinyint(1) DEFAULT NULL,
  `EtatCompteCourriel` tinyint(1) DEFAULT NULL,
  `BottinTel` tinyint(1) DEFAULT NULL,
  `BottinCourriel` tinyint(1) DEFAULT NULL,
  `MembreActif` tinyint(1) DEFAULT '-1',
  `MembreConjoint` tinyint(1) DEFAULT NULL,
  `NoMembreConjoint` int(10) UNSIGNED DEFAULT NULL,
  `Memo` text,
  `Sexe` tinyint(1) DEFAULT NULL,
  `AnneeNaissance` int(4) DEFAULT NULL,
  `PrecisezOrigine` varchar(45) DEFAULT NULL,
  `NomUtilisateur` varchar(15) DEFAULT NULL,
  `MotDePasse` varchar(15) DEFAULT NULL,
  `ProfilApprouver` tinyint(1) DEFAULT '-1',
  `MembrePrinc` tinyint(1) DEFAULT NULL,
  `NomOrganization` varchar(90) DEFAULT NULL,
  `RecevoirCourrielGRP` tinyint(1) DEFAULT NULL,
  `PasCommunication` tinyint(1) DEFAULT NULL,
  `DescriptionOrganizateur` varchar(255) DEFAULT NULL,
  `Date_MAJ_Membre` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `TransfereDe` int(10) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_mensualite`
--

CREATE TABLE `tbl_mensualite` (
  `Id_Mensualite` int(10) UNSIGNED NOT NULL,
  `Id_Pret` int(10) UNSIGNED NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_occupation`
--

CREATE TABLE `tbl_occupation` (
  `NoOccupation` int(10) UNSIGNED NOT NULL,
  `Occupation` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 PACK_KEYS=0;

--
-- Structure de la table `tbl_offre_service_membre`
--

CREATE TABLE `tbl_offre_service_membre` (
  `NoOffreServiceMembre` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED DEFAULT NULL,
  `NoOrganization` int(10) UNSIGNED DEFAULT NULL,
  `NoCategorieSousCategorie` int(10) UNSIGNED DEFAULT NULL,
  `TitreOffreSpecial` varchar(255) DEFAULT NULL,
  `Conditionx` varchar(255) DEFAULT NULL,
  `Disponibilite` varchar(255) DEFAULT NULL,
  `Tarif` varchar(255) DEFAULT NULL,
  `Description` varchar(255) DEFAULT NULL,
  `DateAffichage` date DEFAULT NULL,
  `DateDebut` date DEFAULT NULL,
  `DateFin` date DEFAULT NULL,
  `Approuve` int(1) DEFAULT NULL,
  `OffreSpecial` int(1) DEFAULT NULL,
  `Supprimer` int(1) DEFAULT NULL,
  `Fait` int(1) DEFAULT NULL,
  `ConditionOffre` varchar(255) DEFAULT NULL,
  `NbFoisConsulterOffreMembre` int(10) UNSIGNED DEFAULT '0',
  `DateMAJ_ServiceMembre` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_origine`
--

CREATE TABLE `tbl_origine` (
  `NoOrigine` int(10) UNSIGNED NOT NULL,
  `Origine` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_pointservice`
--

CREATE TABLE `tbl_pointservice` (
  `NoPointService` int(10) UNSIGNED NOT NULL,
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED DEFAULT NULL,
  `NomPointService` varchar(255) CHARACTER SET latin1 DEFAULT NULL,
  `OrdrePointService` tinyint(3) UNSIGNED DEFAULT '0',
  `NoteGrpAchatPageClient` text COLLATE latin1_general_ci,
  `DateMAJ_PointService` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_pointservice_fournisseur`
--

CREATE TABLE `tbl_pointservice_fournisseur` (
  `NoPointServiceFournisseur` int(10) UNSIGNED NOT NULL,
  `NoPointService` int(10) UNSIGNED NOT NULL,
  `NoFournisseur` int(10) UNSIGNED NOT NULL,
  `DateMAJ_PointServiceFournisseur` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_pret`
--

CREATE TABLE `tbl_pret` (
  `Id_Pret` int(10) UNSIGNED NOT NULL,
  `NoMembre` int(10) UNSIGNED NOT NULL,
  `NoMembre_Intermediaire` int(10) UNSIGNED DEFAULT NULL,
  `NoMembre_Responsable` int(10) UNSIGNED NOT NULL,
  `DateDemandePret` datetime DEFAULT NULL,
  `MontantDemande` decimal(8,2) UNSIGNED DEFAULT NULL,
  `RaisonEmprunt` text COLLATE latin1_general_ci,
  `DateComitePret` datetime DEFAULT NULL,
  `Si_PretAccorder` tinyint(3) UNSIGNED DEFAULT NULL,
  `MontantAccorder` decimal(8,2) UNSIGNED DEFAULT NULL,
  `Note` text COLLATE latin1_general_ci,
  `Recommandation` text COLLATE latin1_general_ci,
  `TautInteretAnnuel` decimal(2,2) UNSIGNED DEFAULT NULL,
  `DatePret` datetime DEFAULT NULL,
  `NbreMois` int(10) UNSIGNED DEFAULT NULL,
  `NbrePaiement` int(10) UNSIGNED DEFAULT NULL,
  `DateMAJ_Pret` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_produit`
--

CREATE TABLE `tbl_produit` (
  `NoProduit` int(10) UNSIGNED NOT NULL,
  `NoTitre` int(10) UNSIGNED NOT NULL,
  `NoOrganization` int(10) UNSIGNED NOT NULL,
  `NomProduit` varchar(80) CHARACTER SET latin1 DEFAULT NULL,
  `TaxableF` tinyint(1) UNSIGNED DEFAULT '0',
  `TaxableP` tinyint(1) UNSIGNED DEFAULT '0',
  `Visible_Produit` tinyint(1) UNSIGNED DEFAULT '0',
  `DateMAJ_Produit` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_provenance`
--

CREATE TABLE `tbl_provenance` (
  `NoProvenance` int(10) UNSIGNED NOT NULL,
  `Provenance` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_region`
--

CREATE TABLE `tbl_region` (
  `NoRegion` int(10) UNSIGNED NOT NULL,
  `Region` varchar(60) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_revenu_familial`
--

CREATE TABLE `tbl_revenu_familial` (
  `NoRevenuFamilial` int(10) UNSIGNED NOT NULL,
  `Revenu` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_situation_maison`
--

CREATE TABLE `tbl_situation_maison` (
  `NoSituationMaison` int(10) UNSIGNED NOT NULL,
  `Situation` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_sous_categorie`
--

CREATE TABLE `tbl_sous_categorie` (
  `NoSousCategorie` char(2) NOT NULL DEFAULT '',
  `NoCategorie` int(10) UNSIGNED NOT NULL DEFAULT '0',
  `TitreSousCategorie` varchar(255) DEFAULT NULL,
  `Supprimer` int(1) DEFAULT NULL,
  `Approuver` int(1) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_taxe`
--

CREATE TABLE `tbl_taxe` (
  `NoTaxe` int(10) UNSIGNED NOT NULL,
  `TauxTaxePro` double UNSIGNED DEFAULT NULL,
  `NoTaxePro` varchar(85) CHARACTER SET latin1 DEFAULT NULL,
  `TauxTaxeFed` double UNSIGNED DEFAULT NULL,
  `NoTaxeFed` varchar(85) CHARACTER SET latin1 DEFAULT NULL,
  `TauxMajoration` double UNSIGNED DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_titre`
--

CREATE TABLE `tbl_titre` (
  `NoTitre` int(10) UNSIGNED NOT NULL,
  `Titre` varchar(50) CHARACTER SET latin1 DEFAULT NULL,
  `Visible_Titre` tinyint(1) UNSIGNED DEFAULT NULL,
  `DateMAJ_Titre` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci PACK_KEYS=0;

--
-- Structure de la table `tbl_type_communication`
--

CREATE TABLE `tbl_type_communication` (
  `NoTypeCommunication` int(10) UNSIGNED NOT NULL,
  `TypeCommunication` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 PACK_KEYS=0;

--
-- Structure de la table `tbl_type_compte`
--

CREATE TABLE `tbl_type_compte` (
  `NoMembre` int(10) UNSIGNED NOT NULL DEFAULT '0',
  `OrganizateurSimple` int(1) DEFAULT NULL,
  `Admin` int(1) DEFAULT NULL,
  `AdminChef` int(1) DEFAULT NULL,
  `Reseau` int(1) DEFAULT NULL,
  `SPIP` int(10) UNSIGNED DEFAULT '0',
  `AdminPointService` int(1) DEFAULT '0',
  `AdminOrdPointService` int(1) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1 PACK_KEYS=0;

--
-- Structure de la table `tbl_type_fichier`
--

CREATE TABLE `tbl_type_fichier` (
  `Id_TypeFichier` int(10) UNSIGNED NOT NULL,
  `TypeFichier` varchar(80) COLLATE latin1_general_ci DEFAULT NULL,
  `DateMAJ_TypeFichier` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_type_tel`
--

CREATE TABLE `tbl_type_tel` (
  `NoTypeTel` int(10) UNSIGNED NOT NULL,
  `TypeTel` varchar(35) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

--
-- Structure de la table `tbl_versement`
--

CREATE TABLE `tbl_versement` (
  `Id_Versement` int(10) UNSIGNED NOT NULL,
  `Id_Mensualite` int(10) UNSIGNED NOT NULL,
  `MontantVersement` decimal(8,2) UNSIGNED DEFAULT NULL,
  `DateMAJ_Versement` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1 COLLATE=latin1_general_ci;

--
-- Structure de la table `tbl_ville`
--

CREATE TABLE `tbl_ville` (
  `NoVille` int(10) UNSIGNED NOT NULL,
  `Ville` varchar(60) DEFAULT NULL,
  `NoRegion` int(10) UNSIGNED DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;


--
-- Index pour les tables déchargées
--

--
-- Index pour la table `tbl_organization`
--
ALTER TABLE `tbl_organization`
  ADD PRIMARY KEY (`NoOrganization`),
  ADD KEY `fk_tbl_organization_tbl_region1_idx` (`NoRegion`),
  ADD KEY `fk_tbl_organization_tbl_ville1_idx` (`NoVille`),
  ADD KEY `fk_tbl_organization_tbl_arrondissement1_idx` (`NoArrondissement`),
  ADD KEY `fk_tbl_organization_tbl_cartier1_idx` (`NoCartier`);

--
-- Index pour la table `tbl_achat_ponctuel`
--
ALTER TABLE `tbl_achat_ponctuel`
  ADD PRIMARY KEY (`NoAchatPonctuel`),
  ADD KEY `fk_tbl_achat_ponctuel_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_achat_ponctuel_produit`
--
ALTER TABLE `tbl_achat_ponctuel_produit`
  ADD PRIMARY KEY (`NoAchatPonctuelProduit`),
  ADD UNIQUE KEY `UniqueAchatPoncProduit` (`NoAchatPonctuel`,`NoFournisseurProduit`),
  ADD KEY `fk_tbl_achat_ponctuel_produit_tbl_achat_ponctuel1_idx` (`NoAchatPonctuel`),
  ADD KEY `fk_tbl_achat_ponctuel_produit_tbl_fournisseur_produit1_idx` (`NoFournisseurProduit`);

--
-- Index pour la table `tbl_arrondissement`
--
ALTER TABLE `tbl_arrondissement`
  ADD PRIMARY KEY (`NoArrondissement`),
  ADD KEY `fk_tbl_arrondissement_tbl_ville1_idx` (`NoVille`);

--
-- Index pour la table `tbl_cartier`
--
ALTER TABLE `tbl_cartier`
  ADD PRIMARY KEY (`NoCartier`),
  ADD KEY `fk_tbl_cartier_tbl_arrondissement1_idx` (`NoArrondissement`);

--
-- Index pour la table `tbl_categorie`
--
ALTER TABLE `tbl_categorie`
  ADD PRIMARY KEY (`NoCategorie`);

--
-- Index pour la table `tbl_categorie_sous_categorie`
--
ALTER TABLE `tbl_categorie_sous_categorie`
  ADD PRIMARY KEY (`NoCategorieSousCategorie`),
  ADD KEY `fk_tbl_categorie_sous_categorie_tbl_sous_categorie1_idx` (`NoSousCategorie`),
  ADD KEY `fk_tbl_categorie_sous_categorie_tbl_categorie1_idx` (`NoCategorie`);
ALTER TABLE `tbl_categorie_sous_categorie` ADD FULLTEXT KEY `RchFullText_TitreDescrip` (`TitreOffre`,`Description`);

--
-- Index pour la table `tbl_commande`
--
ALTER TABLE `tbl_commande`
  ADD PRIMARY KEY (`NoCommande`),
  ADD KEY `fk_tbl_commande_tbl_pointservice1_idx` (`NoPointService`);

--
-- Index pour la table `tbl_commande_membre`
--
ALTER TABLE `tbl_commande_membre`
  ADD PRIMARY KEY (`NoCommandeMembre`),
  ADD KEY `fk_tbl_commande_membre_tbl_commande1_idx` (`NoCommande`),
  ADD KEY `fk_tbl_commande_membre_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_commande_membre_produit`
--
ALTER TABLE `tbl_commande_membre_produit`
  ADD PRIMARY KEY (`NoCmdMbProduit`),
  ADD KEY `fk_tbl_commande_membre_produit_tbl_commande_membre1_idx` (`NoCommandeMembre`),
  ADD KEY `fk_tbl_commande_membre_produit_tbl_fournisseur_produit_comm_idx` (`NoFournisseurProduitCommande`);

--
-- Index pour la table `tbl_commentaire`
--
ALTER TABLE `tbl_commentaire`
  ADD PRIMARY KEY (`NoCommentaire`),
  ADD KEY `fk_tbl_commentaire_tbl_pointservice1_idx` (`NoPointService`),
  ADD KEY `fk_tbl_commentaire_tbl_offre_service_membre1_idx` (`NoOffreServiceMembre`),
  ADD KEY `fk_tbl_commentaire_tbl_demande_service1_idx` (`NoDemandeService`),
  ADD KEY `fk_tbl_commentaire_tbl_pointservice2_idx` (`NoMembreSource`),
  ADD KEY `fk_tbl_commentaire_tbl_pointservice3_idx` (`NoMembreViser`);

--
-- Index pour la table `tbl_demande_service`
--
ALTER TABLE `tbl_demande_service`
  ADD PRIMARY KEY (`NoDemandeService`),
  ADD KEY `fk_tbl_demande_service_tbl_membre1_idx` (`NoMembre`),
  ADD KEY `fk_tbl_demande_service_tbl_organization1_idx` (`NoOrganization`);
ALTER TABLE `tbl_demande_service` ADD FULLTEXT KEY `tbl_demande_service_index1460` (`TitreDemande`,`Description`);

--
-- Index pour la table `tbl_dmd_adhesion`
--
ALTER TABLE `tbl_dmd_adhesion`
  ADD PRIMARY KEY (`NoDmdAdhesion`),
  ADD KEY `fk_tbl_dmd_adhesion_tbl_organization1_idx` (`NoOrganization`);

--
-- Index pour la table `tbl_droits_admin`
--
ALTER TABLE `tbl_droits_admin`
  ADD PRIMARY KEY (`NoMembre`),
  ADD KEY `fk_tbl_droits_admin_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_echange_service`
--
ALTER TABLE `tbl_echange_service`
  ADD PRIMARY KEY (`NoEchangeService`),
  ADD KEY `Index_Teste` (`NoEchangeService`,`NoMembreVendeur`,`NoMembreAcheteur`,`TypeEchange`),
  ADD KEY `fk_tbl_echange_service_tbl_membre1_idx` (`NoMembreVendeur`),
  ADD KEY `fk_tbl_echange_service_tbl_membre2_idx` (`NoMembreAcheteur`),
  ADD KEY `fk_tbl_echange_service_tbl_offre_service_membre1_idx` (`NoOffreServiceMembre`),
  ADD KEY `fk_tbl_echange_service_tbl_demande_service1_idx` (`NoDemandeService`),
  ADD KEY `fk_tbl_echange_service_tbl_pointservice1_idx` (`NoPointService`);

--
-- Index pour la table `tbl_fichier`
--
ALTER TABLE `tbl_fichier`
  ADD PRIMARY KEY (`Id_Fichier`),
  ADD KEY `fk_tbl_fichier_tbl_type_fichier1_idx` (`Id_TypeFichier`),
  ADD KEY `fk_tbl_fichier_tbl_organization1_idx` (`NoOrganization`);

--
-- Index pour la table `tbl_fournisseur`
--
ALTER TABLE `tbl_fournisseur`
  ADD PRIMARY KEY (`NoFournisseur`),
  ADD KEY `fk_tbl_fournisseur_tbl_organization1_idx` (`NoOrganization`);

--
-- Index pour la table `tbl_fournisseur_produit`
--
ALTER TABLE `tbl_fournisseur_produit`
  ADD PRIMARY KEY (`NoFournisseurProduit`),
  ADD UNIQUE KEY `UniqueFournisseurProduit` (`NoFournisseur`,`NoProduit`),
  ADD KEY `fk_tbl_fournisseur_produit_tbl_fournisseur1_idx` (`NoFournisseur`),
  ADD KEY `fk_tbl_fournisseur_produit_tbl_produit1_idx` (`NoProduit`);

--
-- Index pour la table `tbl_fournisseur_produit_commande`
--
ALTER TABLE `tbl_fournisseur_produit_commande`
  ADD PRIMARY KEY (`NoFournisseurProduitCommande`),
  ADD UNIQUE KEY `Unique_Produit` (`NoCommande`,`NoFournisseurProduit`),
  ADD KEY `fk_tbl_fournisseur_produit_commande_tbl_commande1_idx` (`NoCommande`),
  ADD KEY `fk_tbl_fournisseur_produit_commande_tbl_fournisseur_produit_idx` (`NoFournisseurProduit`);

--
-- Index pour la table `tbl_fournisseur_produit_pointservice`
--
ALTER TABLE `tbl_fournisseur_produit_pointservice`
  ADD PRIMARY KEY (`NoFournisseurProduitPointservice`),
  ADD UNIQUE KEY `UniqueProduitFournPointService` (`NoFournisseurProduit`,`NoPointService`),
  ADD KEY `fk_tbl_fournisseur_produit_pointservice_tbl_pointservice1_idx` (`NoPointService`),
  ADD KEY `fk_tbl_fournisseur_produit_pointservice_tbl_fournisseur_pro_idx` (`NoFournisseurProduit`);

--
-- Index pour la table `tbl_info_logiciel_bd`
--
ALTER TABLE `tbl_info_logiciel_bd`
  ADD PRIMARY KEY (`NoInfoLogicielBD`);

--
-- Index pour la table `tbl_log_acces`
--
ALTER TABLE `tbl_log_acces`
  ADD PRIMARY KEY (`Id_log_acces`),
  ADD KEY `fk_tbl_log_acces_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_membre`
--
ALTER TABLE `tbl_membre`
  ADD PRIMARY KEY (`NoMembre`),
  ADD KEY `fk_tbl_membre_tbl_organization_idx` (`NoOrganization`),
  ADD KEY `fk_tbl_membre_tbl_cartier1_idx` (`NoCartier`),
  ADD KEY `fk_tbl_membre_tbl_type_communication1_idx` (`NoTypeCommunication`),
  ADD KEY `fk_tbl_membre_tbl_occupation1_idx` (`NoOccupation`),
  ADD KEY `fk_tbl_membre_tbl_origine1_idx` (`NoOrigine`),
  ADD KEY `fk_tbl_membre_tbl_situation_maison1_idx` (`NoSituationMaison`),
  ADD KEY `fk_tbl_membre_tbl_provenance1_idx` (`NoProvenance`),
  ADD KEY `fk_tbl_membre_tbl_revenu_familial1_idx` (`NoRevenuFamilial`),
  ADD KEY `fk_tbl_membre_tbl_arrondissement1_idx` (`NoArrondissement`),
  ADD KEY `fk_tbl_membre_tbl_ville1_idx` (`NoVille`),
  ADD KEY `fk_tbl_membre_tbl_type_tel2_idx` (`NoTypeTel1`),
  ADD KEY `fk_tbl_membre_tbl_type_tel3_idx` (`NoTypeTel2`),
  ADD KEY `fk_tbl_membre_tbl_region1_idx` (`NoRegion`),
  ADD KEY `fk_tbl_membre_tbl_pointservice1_idx` (`NoPointService`),
  ADD KEY `fk_tbl_membre_tbl_type_tel1_idx` (`NoTypeTel3`);
ALTER TABLE `tbl_membre` ADD FULLTEXT KEY `rch` (`Nom`,`Prenom`,`Telephone1`,`Telephone2`,`Telephone3`,`Courriel`,`NomUtilisateur`,`Memo`);

--
-- Index pour la table `tbl_mensualite`
--
ALTER TABLE `tbl_mensualite`
  ADD PRIMARY KEY (`Id_Mensualite`),
  ADD KEY `fk_tbl_mensualite_tbl_Pret1_idx` (`Id_Pret`);

--
-- Index pour la table `tbl_occupation`
--
ALTER TABLE `tbl_occupation`
  ADD PRIMARY KEY (`NoOccupation`);

--
-- Index pour la table `tbl_offre_service_membre`
--
ALTER TABLE `tbl_offre_service_membre`
  ADD PRIMARY KEY (`NoOffreServiceMembre`),
  ADD KEY `fk_tbl_offre_service_membre_tbl_membre1_idx` (`NoMembre`),
  ADD KEY `fk_tbl_offre_service_membre_tbl_organization1_idx` (`NoOrganization`),
  ADD KEY `fk_tbl_offre_service_membre_tbl_categorie_sous_categorie1_idx` (`NoCategorieSousCategorie`);
ALTER TABLE `tbl_offre_service_membre` ADD FULLTEXT KEY `RchFullText_OffreSpe` (`TitreOffreSpecial`,`Description`);

--
-- Index pour la table `tbl_origine`
--
ALTER TABLE `tbl_origine`
  ADD PRIMARY KEY (`NoOrigine`);

--
-- Index pour la table `tbl_pointservice`
--
ALTER TABLE `tbl_pointservice`
  ADD PRIMARY KEY (`NoPointService`),
  ADD KEY `fk_tbl_pointservice_tbl_organization1_idx` (`NoOrganization`),
  ADD KEY `fk_tbl_pointservice_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_pointservice_fournisseur`
--
ALTER TABLE `tbl_pointservice_fournisseur`
  ADD PRIMARY KEY (`NoPointServiceFournisseur`),
  ADD KEY `fk_tbl_pointservice_fournisseur_tbl_fournisseur1_idx` (`NoFournisseur`),
  ADD KEY `fk_tbl_pointservice_fournisseur_tbl_pointservice1_idx` (`NoPointService`);

--
-- Index pour la table `tbl_pret`
--
ALTER TABLE `tbl_pret`
  ADD PRIMARY KEY (`Id_Pret`),
  ADD KEY `fk_tbl_pret_tbl_membre1_idx` (`NoMembre`),
  ADD KEY `fk_tbl_pret_tbl_membre2_idx` (`NoMembre_Intermediaire`),
  ADD KEY `fk_tbl_pret_tbl_membre3_idx` (`NoMembre_Responsable`);

--
-- Index pour la table `tbl_produit`
--
ALTER TABLE `tbl_produit`
  ADD PRIMARY KEY (`NoProduit`),
  ADD KEY `fk_tbl_produit_tbl_titre1_idx` (`NoTitre`),
  ADD KEY `fk_tbl_produit_tbl_organization1_idx` (`NoOrganization`);

--
-- Index pour la table `tbl_provenance`
--
ALTER TABLE `tbl_provenance`
  ADD PRIMARY KEY (`NoProvenance`);

--
-- Index pour la table `tbl_region`
--
ALTER TABLE `tbl_region`
  ADD PRIMARY KEY (`NoRegion`);

--
-- Index pour la table `tbl_revenu_familial`
--
ALTER TABLE `tbl_revenu_familial`
  ADD PRIMARY KEY (`NoRevenuFamilial`);

--
-- Index pour la table `tbl_situation_maison`
--
ALTER TABLE `tbl_situation_maison`
  ADD PRIMARY KEY (`NoSituationMaison`);

--
-- Index pour la table `tbl_sous_categorie`
--
ALTER TABLE `tbl_sous_categorie`
  ADD PRIMARY KEY (`NoSousCategorie`,`NoCategorie`),
  ADD KEY `fk_tbl_sous_categorie_tbl_categorie1_idx` (`NoCategorie`);

--
-- Index pour la table `tbl_taxe`
--
ALTER TABLE `tbl_taxe`
  ADD PRIMARY KEY (`NoTaxe`);

--
-- Index pour la table `tbl_titre`
--
ALTER TABLE `tbl_titre`
  ADD PRIMARY KEY (`NoTitre`);

--
-- Index pour la table `tbl_type_communication`
--
ALTER TABLE `tbl_type_communication`
  ADD PRIMARY KEY (`NoTypeCommunication`);

--
-- Index pour la table `tbl_type_compte`
--
ALTER TABLE `tbl_type_compte`
  ADD PRIMARY KEY (`NoMembre`),
  ADD KEY `fk_tbl_type_compte_tbl_membre1_idx` (`NoMembre`);

--
-- Index pour la table `tbl_type_fichier`
--
ALTER TABLE `tbl_type_fichier`
  ADD PRIMARY KEY (`Id_TypeFichier`);

--
-- Index pour la table `tbl_type_tel`
--
ALTER TABLE `tbl_type_tel`
  ADD PRIMARY KEY (`NoTypeTel`);

--
-- Index pour la table `tbl_versement`
--
ALTER TABLE `tbl_versement`
  ADD PRIMARY KEY (`Id_Versement`),
  ADD KEY `fk_tbl_versement_tbl_mensualite1_idx` (`Id_Mensualite`);

--
-- Index pour la table `tbl_ville`
--
ALTER TABLE `tbl_ville`
  ADD PRIMARY KEY (`NoVille`),
  ADD KEY `fk_tbl_ville_tbl_region1_idx` (`NoRegion`);

--
-- AUTO_INCREMENT pour les tables déchargées
--

--
-- AUTO_INCREMENT pour la table `tbl_organization`
--
ALTER TABLE `tbl_organization`
  MODIFY `NoOrganization` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=121;

--
-- AUTO_INCREMENT pour la table `tbl_achat_ponctuel`
--
ALTER TABLE `tbl_achat_ponctuel`
  MODIFY `NoAchatPonctuel` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=276;

--
-- AUTO_INCREMENT pour la table `tbl_achat_ponctuel_produit`
--
ALTER TABLE `tbl_achat_ponctuel_produit`
  MODIFY `NoAchatPonctuelProduit` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=537;

--
-- AUTO_INCREMENT pour la table `tbl_arrondissement`
--
ALTER TABLE `tbl_arrondissement`
  MODIFY `NoArrondissement` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=73;

--
-- AUTO_INCREMENT pour la table `tbl_cartier`
--
ALTER TABLE `tbl_cartier`
  MODIFY `NoCartier` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=30;

--
-- AUTO_INCREMENT pour la table `tbl_categorie`
--
ALTER TABLE `tbl_categorie`
  MODIFY `NoCategorie` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=1000;

--
-- AUTO_INCREMENT pour la table `tbl_categorie_sous_categorie`
--
ALTER TABLE `tbl_categorie_sous_categorie`
  MODIFY `NoCategorieSousCategorie` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=1381;

--
-- AUTO_INCREMENT pour la table `tbl_commande`
--
ALTER TABLE `tbl_commande`
  MODIFY `NoCommande` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=308;

--
-- AUTO_INCREMENT pour la table `tbl_commande_membre`
--
ALTER TABLE `tbl_commande_membre`
  MODIFY `NoCommandeMembre` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6211;

--
-- AUTO_INCREMENT pour la table `tbl_commande_membre_produit`
--
ALTER TABLE `tbl_commande_membre_produit`
  MODIFY `NoCmdMbProduit` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=72290;

--
-- AUTO_INCREMENT pour la table `tbl_commentaire`
--
ALTER TABLE `tbl_commentaire`
  MODIFY `NoCommentaire` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=383;

--
-- AUTO_INCREMENT pour la table `tbl_demande_service`
--
ALTER TABLE `tbl_demande_service`
  MODIFY `NoDemandeService` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3212;

--
-- AUTO_INCREMENT pour la table `tbl_dmd_adhesion`
--
ALTER TABLE `tbl_dmd_adhesion`
  MODIFY `NoDmdAdhesion` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=1065;

--
-- AUTO_INCREMENT pour la table `tbl_echange_service`
--
ALTER TABLE `tbl_echange_service`
  MODIFY `NoEchangeService` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=107322;

--
-- AUTO_INCREMENT pour la table `tbl_fichier`
--
ALTER TABLE `tbl_fichier`
  MODIFY `Id_Fichier` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=503;

--
-- AUTO_INCREMENT pour la table `tbl_fournisseur`
--
ALTER TABLE `tbl_fournisseur`
  MODIFY `NoFournisseur` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=142;

--
-- AUTO_INCREMENT pour la table `tbl_fournisseur_produit`
--
ALTER TABLE `tbl_fournisseur_produit`
  MODIFY `NoFournisseurProduit` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4386;

--
-- AUTO_INCREMENT pour la table `tbl_fournisseur_produit_commande`
--
ALTER TABLE `tbl_fournisseur_produit_commande`
  MODIFY `NoFournisseurProduitCommande` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=74860;

--
-- AUTO_INCREMENT pour la table `tbl_fournisseur_produit_pointservice`
--
ALTER TABLE `tbl_fournisseur_produit_pointservice`
  MODIFY `NoFournisseurProduitPointservice` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7946;

--
-- AUTO_INCREMENT pour la table `tbl_info_logiciel_bd`
--
ALTER TABLE `tbl_info_logiciel_bd`
  MODIFY `NoInfoLogicielBD` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=3;

--
-- AUTO_INCREMENT pour la table `tbl_log_acces`
--
ALTER TABLE `tbl_log_acces`
  MODIFY `Id_log_acces` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=318179;

--
-- AUTO_INCREMENT pour la table `tbl_membre`
--
ALTER TABLE `tbl_membre`
  MODIFY `NoMembre` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=10144;

--
-- AUTO_INCREMENT pour la table `tbl_mensualite`
--
ALTER TABLE `tbl_mensualite`
  MODIFY `Id_Mensualite` int(10) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `tbl_occupation`
--
ALTER TABLE `tbl_occupation`
  MODIFY `NoOccupation` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=8;

--
-- AUTO_INCREMENT pour la table `tbl_offre_service_membre`
--
ALTER TABLE `tbl_offre_service_membre`
  MODIFY `NoOffreServiceMembre` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=73151;

--
-- AUTO_INCREMENT pour la table `tbl_origine`
--
ALTER TABLE `tbl_origine`
  MODIFY `NoOrigine` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT pour la table `tbl_pointservice`
--
ALTER TABLE `tbl_pointservice`
  MODIFY `NoPointService` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=35;

--
-- AUTO_INCREMENT pour la table `tbl_pointservice_fournisseur`
--
ALTER TABLE `tbl_pointservice_fournisseur`
  MODIFY `NoPointServiceFournisseur` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=140;

--
-- AUTO_INCREMENT pour la table `tbl_pret`
--
ALTER TABLE `tbl_pret`
  MODIFY `Id_Pret` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT pour la table `tbl_produit`
--
ALTER TABLE `tbl_produit`
  MODIFY `NoProduit` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4194;

--
-- AUTO_INCREMENT pour la table `tbl_provenance`
--
ALTER TABLE `tbl_provenance`
  MODIFY `NoProvenance` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT pour la table `tbl_region`
--
ALTER TABLE `tbl_region`
  MODIFY `NoRegion` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=18;

--
-- AUTO_INCREMENT pour la table `tbl_revenu_familial`
--
ALTER TABLE `tbl_revenu_familial`
  MODIFY `NoRevenuFamilial` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT pour la table `tbl_situation_maison`
--
ALTER TABLE `tbl_situation_maison`
  MODIFY `NoSituationMaison` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7;

--
-- AUTO_INCREMENT pour la table `tbl_taxe`
--
ALTER TABLE `tbl_taxe`
  MODIFY `NoTaxe` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=2;

--
-- AUTO_INCREMENT pour la table `tbl_titre`
--
ALTER TABLE `tbl_titre`
  MODIFY `NoTitre` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=53;

--
-- AUTO_INCREMENT pour la table `tbl_type_communication`
--
ALTER TABLE `tbl_type_communication`
  MODIFY `NoTypeCommunication` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT pour la table `tbl_type_fichier`
--
ALTER TABLE `tbl_type_fichier`
  MODIFY `Id_TypeFichier` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=14;

--
-- AUTO_INCREMENT pour la table `tbl_type_tel`
--
ALTER TABLE `tbl_type_tel`
  MODIFY `NoTypeTel` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=6;

--
-- AUTO_INCREMENT pour la table `tbl_versement`
--
ALTER TABLE `tbl_versement`
  MODIFY `Id_Versement` int(10) UNSIGNED NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT pour la table `tbl_ville`
--
ALTER TABLE `tbl_ville`
  MODIFY `NoVille` int(10) UNSIGNED NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=99906;
COMMIT;
