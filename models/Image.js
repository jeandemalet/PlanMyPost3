

const mongoose = require('mongoose');

const ImageSchema = new mongoose.Schema({
    galleryId: {
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Gallery',
        required: true,
        index: true // Indexer pour recherche rapide par galerie
    },
    originalFilename: { // Nom original du fichier uploadé
        type: String,
        required: true,
        trim: true
    },
    filename: { // Nom unique du fichier stocké sur le serveur
        type: String,
        required: true,
        unique: true // Assurer l'unicité du nom de fichier serveur
    },
    // NOUVEAU: Chemin vers le fichier original non modifié (qualité 100%)
    originalPath: {
        type: String,
        required: true
    },
    // MODIFIÉ: Ce champ pointera désormais vers la "copie de travail" (qualité ~85%)
    path: {
        type: String,
        required: true
    },
    // MODIFIÉ: Ce champ pointera vers la miniature ultra-optimisée (qualité ~40%)
    thumbnailPath: {
        type: String,
        required: true
    },
    // AJOUTEZ CES DEUX CHAMPS
    webpPath: { type: String },
    thumbnailWebpPath: { type: String },
    mimeType: {
        type: String
    },
    size: { // Taille en octets
        type: Number
    },
    // AJOUTEZ CES DEUX CHAMPS
    width: { type: Number },
    height: { type: Number },
    exifDateTimeOriginal: { // Date/heure extraite des métadonnées EXIF
        type: Date
    },
    fileLastModified: { // Date de dernière modification du fichier source (si disponible)
        type: Date
    },
    isCroppedVersion: { // True si cette image est le résultat d'un recadrage
        type: Boolean,
        default: false
    },
    parentImageId: { // Si isCroppedVersion est true, référence l'ID de l'image originale
        type: mongoose.Schema.Types.ObjectId,
        ref: 'Image'
    },
    cropInfo: { // Description textuelle du recadrage appliqué (ex: "barres_4x5", "split_gauche")
        type: String
    },
    uploadDate: { // Date d'upload de cette image (originale ou recadrée) sur le serveur
        type: Date,
        default: Date.now
    }
});

// Index composite pour vérifier rapidement les doublons (même nom original dans la même galerie)
ImageSchema.index({ galleryId: 1, originalFilename: 1 });
// Index pour trouver les images d'une galerie
ImageSchema.index({ galleryId: 1, uploadDate: 1 }); // Utile pour tri par date d'upload
ImageSchema.index({ galleryId: 1, isCroppedVersion: 1 }); // Utile pour filtrer les originales

// === INDEX OPTIMIZATIONS SUPPLÉMENTAIRES ===
// Index pour les requêtes de tri par taille de fichier
ImageSchema.index({ galleryId: 1, size: -1 });
// Index pour les requêtes de tri par dimensions
ImageSchema.index({ galleryId: 1, width: -1, height: -1 });
// Index pour rechercher par type MIME
ImageSchema.index({ galleryId: 1, mimeType: 1 });
// Index pour les images recadrées et leur parent
ImageSchema.index({ parentImageId: 1, isCroppedVersion: 1 });
// Index pour les requêtes par date EXIF
ImageSchema.index({ galleryId: 1, exifDateTimeOriginal: -1 });

module.exports = mongoose.model('Image', ImageSchema);
