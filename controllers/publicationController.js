// ===============================
//  Fichier: controllers\publicationController.js
// ===============================
const Publication = require('../models/Publication');
const Gallery = require('../models/Gallery');
const Image = require('../models/Image'); // Ajouté pour peupler les images de la Publication
const mongoose = require('mongoose');
const archiver = require('archiver'); // Ajouté pour le ZIP
const path = require('path');       // Ajouté pour les chemins de fichiers
const fs = require('fs');           // Ajouté pour vérifier l'existence des fichiers

const UPLOAD_DIR = path.join(__dirname, '..', 'uploads'); // S'assurer que UPLOAD_DIR est défini

exports.createPublication = async (req, res) => {
    const { galleryId } = req.params;

    try {
        const gallery = await Gallery.findById(galleryId);
        if (!gallery) {
            return res.status(404).json({ message: `Gallery with ID ${galleryId} not found.` });
        }

        const existingPublications = await Publication.find({ galleryId: galleryId }).select('index letter').sort({ index: 1 }).lean();
        
        // ======================= LOG À AJOUTER (1/3) =======================
        console.log(`[DEBUG] createPublication: Galerie ${galleryId}. Publications existantes trouvées:`, existingPublications.map(p => p.letter).join(', ') || 'Aucune');
        // =====================================================================
        
        const existingIndices = new Set(existingPublications.map(p => p.index));
        
        // CORRECTION : Trouver le PREMIER index libre (combler les trous)
        let nextAvailableIndex = 0;
        while (existingIndices.has(nextAvailableIndex)) {
            // Cette boucle s'arrêtera au premier "trou"
            // Si A(0), B(1), D(3) existent, elle s'arrêtera à nextAvailableIndex = 2 (C)
            nextAvailableIndex++;
            if (nextAvailableIndex >= 26) break; // Sécurité pour éviter une boucle infinie
        }

        // ======================= LOG À AJOUTER (2/3) =======================
        console.log(`[DEBUG] createPublication: Prochain index disponible calculé: ${nextAvailableIndex}`);
        // =====================================================================

        if (nextAvailableIndex >= 26) {
            return res.status(400).json({ message: 'Maximum number of Publications (A-Z) reached for this gallery.' });
        }
        
        const letter = String.fromCharCode('A'.charCodeAt(0) + nextAvailableIndex);

        // ======================= LOG À AJOUTER (3/3) =======================
        console.log(`[DEBUG] createPublication: Création de la Publication avec la lettre: ${letter}`);
        // =====================================================================

        const alreadyExists = existingPublications.find(p => p.letter === letter);
        if (alreadyExists) {
            console.warn(`Attempt to create Publication ${letter} (index ${nextAvailableIndex}) which already exists for gallery ${galleryId}.`);
            const populatedExistingPublication = await Publication.findById(alreadyExists._id).populate('images.imageId');
            return res.status(200).json(populatedExistingPublication);
        }

        const newPublication = new Publication({
            galleryId,
            letter,
            index: nextAvailableIndex,
            images: [],
            descriptionText: ''
        });
        await newPublication.save();

        // Mettre à jour l'indice de la galerie pour la prochaine suggestion
        const currentIndicesAfterCreation = new Set([...existingIndices, nextAvailableIndex]);
        let galleryNextHintIndex = 0;
        while (currentIndicesAfterCreation.has(galleryNextHintIndex)) {
            galleryNextHintIndex++;
            if (galleryNextHintIndex >= 26) break; // Sécurité
        }
        
        gallery.nextPublicationIndex = galleryNextHintIndex;
        await gallery.save(); 

        const populatedPublication = await Publication.findById(newPublication._id).populate('images.imageId');
        res.status(201).json(populatedPublication);

    } catch (error) {
        console.error("Error creating publication:", error);
        if (error.name === 'ValidationError') {
            res.status(400).json({ message: `Validation Error: ${error.message}` });
        } else if (error.code === 11000) { 
             res.status(409).json({ message: `Conflict: Publication with this letter/index likely already exists (DB Error). Original error: ${error.message}` });
        }
        else {
            res.status(500).json({ message: 'Server error creating publication.' });
        }
    }
};

exports.getPublicationsForGallery = async (req, res) => {
    const { galleryId } = req.params;
    try {
        const publications = await Publication.find({ galleryId: galleryId })
                              .populate('images.imageId') 
                              .sort({ index: 1 }); 
        res.json(publications);
    } catch (error) {
        console.error("Error getting publications for gallery:", error);
        res.status(500).send('Server error retrieving publications.');
    }
};

exports.updatePublication = async (req, res) => {
    const { galleryId, publicationId } = req.params;
    const { images, descriptionText, autoCropSettings } = req.body;

    if (images !== undefined && !Array.isArray(images)) {
        return res.status(400).send('Invalid images data format. Expected an array if provided.');
    }
    
    const updatePayload = {};

    if (Array.isArray(images)) {
        const validatedImages = [];
        for (let i = 0; i < images.length; i++) {
            const imgEntry = images[i];
            if (!imgEntry || !mongoose.Types.ObjectId.isValid(imgEntry.imageId)) {
                console.warn(`Invalid imageId found in update request for Publication ${publicationId}:`, imgEntry);
                continue; 
            }
            validatedImages.push({
                imageId: imgEntry.imageId,
                order: i 
            });
        }
        updatePayload.images = validatedImages;
    }

    if (typeof descriptionText === 'string') {
        updatePayload.descriptionText = descriptionText;
    }
    
    // Gérer la mise à jour des paramètres de recadrage automatique
    if (autoCropSettings && typeof autoCropSettings === 'object') {
        if (autoCropSettings.vertical) {
            updatePayload['autoCropSettings.vertical'] = autoCropSettings.vertical;
        }
        if (autoCropSettings.horizontal) {
            updatePayload['autoCropSettings.horizontal'] = autoCropSettings.horizontal;
        }
    }
    
    if (Object.keys(updatePayload).length === 0) {
        return res.status(400).send('No valid data provided for update.');
    }

    try {
        const updatedPublication = await Publication.findOneAndUpdate(
            { _id: publicationId, galleryId: galleryId }, 
            { $set: updatePayload },  
            { new: true, runValidators: true }     
        ).populate('images.imageId'); 

        if (!updatedPublication) {
            return res.status(404).send('Publication not found or does not belong to the specified gallery.');
        }
        res.json(updatedPublication); 
    } catch (error) {
        console.error("Error updating publication:", error);
         if (error.name === 'ValidationError') {
            res.status(400).send(`Validation Error: ${error.message}`);
        } else {
            res.status(500).send('Server error updating publication.');
        }
    }
};

exports.deletePublication = async (req, res) => {
    const { galleryId, publicationId } = req.params;
    try {
        const result = await Publication.deleteOne({ _id: publicationId, galleryId: galleryId });

        if (result.deletedCount === 0) {
            return res.status(404).send('Publication not found or does not belong to the specified gallery.');
        }
        
        const gallery = await Gallery.findById(galleryId);
        if (gallery) {
            const remainingPublications = await Publication.find({ galleryId: galleryId }).select('index').sort({ index: 1 }).lean();
            const remainingIndices = new Set(remainingPublications.map(p => p.index));
            // CORRECTION : Trouver le PREMIER index libre après suppression
            let nextIndex = 0;
            while (remainingIndices.has(nextIndex)) {
                nextIndex++;
                if (nextIndex >= 26) break; // Sécurité
            }
            gallery.nextPublicationIndex = nextIndex;
            await gallery.save();
        }

        res.status(200).send('Publication deleted successfully.');
    } catch (error) {
        console.error("Error deleting publication:", error);
        res.status(500).send('Server error deleting publication.');
    }
};

exports.exportPublicationImagesAsZip = async (req, res) => {
    const { galleryId, publicationId } = req.params;

    try {
        const [publication, gallery] = await Promise.all([
            Publication.findById(publicationId).populate({
                path: 'images.imageId',
                model: 'Image'
            }),
            Gallery.findById(galleryId).select('name commonDescriptionText').lean() // Ajout de commonDescriptionText
        ]);

        if (!publication || publication.galleryId.toString() !== galleryId) {
            return res.status(404).send('Publication not found or does not belong to the specified gallery.');
        }

        if (!gallery) {
            return res.status(404).send('Gallery not found for this Publication.');
        }

        if (!publication.images || publication.images.length === 0) {
            return res.status(400).send('This Publication contains no images to export.');
        }

        const archive = archiver('zip', {
            zlib: { level: 9 }
        });

        archive.on('warning', function (err) {
            if (err.code === 'ENOENT') {
                console.warn('Archiver warning (ENOENT):', err);
            } else {
                console.error('Archiver warning:', err);
            }
        });
        archive.on('error', function (err) {
            console.error('Archiver error:', err);
            if (!res.headersSent) {
                res.status(500).send({ error: 'Failed to create zip archive.', details: err.message });
            }
        });

        const sanitizedGalleryName = gallery.name.replace(/[^a-zA-Z0-9_.\-]/g, '_');
        const zipFileName = `${sanitizedGalleryName} - Publication ${publication.letter} - Plan My Post.zip`;
        res.attachment(zipFileName);

        archive.pipe(res);

        // --- DÉBUT DE LA NOUVELLE LOGIQUE D'AJOUT DE LA DESCRIPTION ---

        // 1. Préparer le contenu final de la description en remplaçant le placeholder.
        let finalDescription = publication.descriptionText || '';
        if (gallery.commonDescriptionText && finalDescription.includes('{{COMMON_TEXT}}')) {
            finalDescription = finalDescription.replace(/\{\{COMMON_TEXT\}\}/g, gallery.commonDescriptionText);
        }

        // 2. Définir le nom du fichier texte.
        const descriptionFileName = `${sanitizedGalleryName} - Publication ${publication.letter} - Description.txt`;
                
        // 3. Ajouter le fichier au ZIP (seulement si la description finale n'est pas vide).
        if (finalDescription.trim() !== '') {
            archive.append(finalDescription, { name: descriptionFileName });
        }
                
        // --- FIN DE LA NOUVELLE LOGIQUE ---
        
        // Boucle pour ajouter les images avec qualité maximale (originale)
        for (let i = 0; i < publication.images.length; i++) {
            const imageEntry = publication.images[i];
            if (imageEntry.imageId && imageEntry.imageId.originalPath) {
                const imageDoc = imageEntry.imageId;
                // MODIFICATION : Utiliser originalPath pour la meilleure qualité
                const filePath = path.join(UPLOAD_DIR, imageDoc.originalPath);

                if (fs.existsSync(filePath)) {
                    const position = String(i + 1).padStart(2, '0');
                    const extension = path.extname(imageDoc.originalFilename) || '.jpg';
                    const filenameInZip = `${sanitizedGalleryName} - Publication ${publication.letter} - ${position} - Plan My Post${extension}`;
                    archive.file(filePath, { name: filenameInZip });
                } else {
                    console.warn(`Fichier original non trouvé, fallback vers copie de travail: ${filePath}`);
                    // Fallback vers la copie de travail si l'original n'existe pas
                    const fallbackPath = path.join(UPLOAD_DIR, imageDoc.path);
                    if (fs.existsSync(fallbackPath)) {
                        const position = String(i + 1).padStart(2, '0');
                        const extension = path.extname(imageDoc.originalFilename) || '.jpg';
                        const filenameInZip = `${sanitizedGalleryName} - Publication ${publication.letter} - ${position} - Plan My Post${extension}`;
                        archive.file(fallbackPath, { name: filenameInZip });
                    } else {
                        console.warn(`Ni original ni copie de travail trouvés pour l'image: ${imageDoc.originalFilename}`);
                    }
                }
            }
        }

        await archive.finalize();

    } catch (error) {
        console.error(`Error exporting Publication ${publicationId} images:`, error);
        if (!res.headersSent) {
            res.status(500).send('Server error during Publication export.');
        }
    }
};
/*
*
 * Ré-indexe les publications d'une galerie.
 * Supprime les publications vides et compacte la séquence des publications restantes.
 */
exports.cleanupAndResequence = async (req, res) => {
    const { galleryId } = req.params;

    try {
        // 1. Récupérer TOUTES les publications de la galerie, triées par leur index actuel.
        const allPublications = await Publication.find({ galleryId }).sort({ index: 'asc' }).lean();

        if (allPublications.length === 0) {
            return res.status(200).json({ message: 'Aucune publication à nettoyer.' });
        }

        // 2. Séparer les publications pleines et vides.
        const fullPublications = [];
        const idsToDelete = [];
        allPublications.forEach(pub => {
            if (pub.images && pub.images.length > 0) {
                fullPublications.push(pub);
            } else {
                idsToDelete.push(pub._id);
            }
        });

        // 3. Préparer le plan de ré-indexation pour les publications pleines.
        const operations = [];
        let needsUpdate = false;
        fullPublications.forEach((pub, newIndex) => {
            const newLetter = String.fromCharCode('A'.charCodeAt(0) + newIndex);
            // On ne met à jour que si c'est strictement nécessaire.
            if (pub.letter !== newLetter || pub.index !== newIndex) {
                needsUpdate = true;
                operations.push({
                    updateOne: {
                        filter: { _id: pub._id },
                        update: { $set: { letter: newLetter, index: newIndex } }
                    }
                });
            }
        });

        // 4. Exécuter les opérations sur la base de données.
        if (needsUpdate) {
            await Publication.bulkWrite(operations, { ordered: false });
        }

        if (idsToDelete.length > 0) {
            await Publication.deleteMany({ _id: { $in: idsToDelete } });
        }

        // 5. Mettre à jour l'index de la prochaine publication dans la galerie.
        if (needsUpdate || idsToDelete.length > 0) {
            const gallery = await Gallery.findById(galleryId);
            if (gallery) {
                // CORRECTION : Trouver le PREMIER index libre après nettoyage
                const finalIndices = new Set(fullPublications.map((_, index) => index));
                let nextIndex = 0;
                while (finalIndices.has(nextIndex)) {
                    nextIndex++;
                    if (nextIndex >= 26) break; // Sécurité
                }
                gallery.nextPublicationIndex = nextIndex;
                await gallery.save();
            }
        }

        console.log(`[Cleanup] Nettoyage terminé pour la galerie ${galleryId}: ${operations.length} mises à jour, ${idsToDelete.length} suppressions`);
        res.status(200).json({ message: 'Nettoyage et ré-indexation terminés.' });

    } catch (error) {
        console.error("Erreur lors du nettoyage et de la ré-indexation:", error);
        res.status(500).json({ message: 'Erreur serveur lors du nettoyage.' });
    }
};
