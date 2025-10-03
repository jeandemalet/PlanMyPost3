#!/usr/bin/env node
// ===============================
// Script de Migration : Architecture à Trois Niveaux
// ===============================
// Ce script migre les images existantes vers la nouvelle architecture :
// - originalPath : fichier original 100% (déplacé depuis l'ancien path)
// - path : copie de travail ~85% qualité (générée)
// - thumbnailPath : miniature UI ~40% qualité (générée)

const mongoose = require('mongoose');
const Image = require('../models/Image');
const Gallery = require('../models/Gallery');
const sharp = require('sharp');
const fse = require('fs-extra');
const path = require('path');

const UPLOAD_DIR = path.join(__dirname, '..', 'uploads');

// Configuration MongoDB
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/publication-organizer';

async function connectDB() {
    try {
        await mongoose.connect(MONGODB_URI);
        console.log('✅ Connecté à MongoDB');
    } catch (error) {
        console.error('❌ Erreur de connexion MongoDB:', error);
        process.exit(1);
    }
}

async function migrateImages() {
    console.log('🚀 Démarrage de la migration vers l\'architecture à trois niveaux...\n');

    try {
        // Récupérer toutes les images qui n'ont pas encore été migrées
        const imagesToMigrate = await Image.find({
            $or: [
                { originalPath: { $exists: false } },
                { originalPath: null }
            ]
        }).populate('galleryId');

        console.log(`📊 Images à migrer trouvées: ${imagesToMigrate.length}`);

        if (imagesToMigrate.length === 0) {
            console.log('✅ Aucune image à migrer. Migration terminée.');
            return;
        }

        let successCount = 0;
        let errorCount = 0;
        const errors = [];

        for (let i = 0; i < imagesToMigrate.length; i++) {
            const image = imagesToMigrate[i];
            const galleryId = image.galleryId._id || image.galleryId;

            console.log(`\n📸 Migration de l'image ${i + 1}/${imagesToMigrate.length}: ${image.originalFilename}`);

            try {
                const galleryUploadDir = path.join(UPLOAD_DIR, galleryId.toString());
                await fse.ensureDir(galleryUploadDir);

                // Chemins actuels et futurs
                const currentPath = path.join(UPLOAD_DIR, image.path);
                const currentThumbPath = path.join(UPLOAD_DIR, image.thumbnailPath);

                // Nouveaux chemins selon l'architecture à trois niveaux
                const timestamp = Date.now();
                const safeOriginalName = image.originalname || image.originalFilename.replace(/[^a-zA-Z0-9._-]/g, '_');
                const originalFilename = `original-${timestamp}-${safeOriginalName}`;
                const workingFilename = `work-${timestamp}-${safeOriginalName}`;
                const thumbFilename = `thumb-${timestamp}-${safeOriginalName}`;

                const newOriginalPath = path.join(galleryId.toString(), originalFilename);
                const newWorkingPath = path.join(galleryId.toString(), workingFilename);
                const newThumbPath = path.join(galleryId.toString(), thumbFilename);

                // Vérifier que les fichiers actuels existent
                const currentFileExists = await fse.pathExists(currentPath);
                const currentThumbExists = await fse.pathExists(currentThumbPath);

                if (!currentFileExists) {
                    console.warn(`⚠️  Fichier principal manquant: ${currentPath}`);
                    errors.push({
                        imageId: image._id,
                        error: 'Fichier principal manquant',
                        originalFilename: image.originalFilename
                    });
                    errorCount++;
                    continue;
                }

                // 1. Lire le fichier original
                const imageBuffer = await fse.readFile(currentPath);

                // 2. Déplacer vers le nouvel emplacement original (sans ré-encodage)
                const newOriginalFullPath = path.join(UPLOAD_DIR, newOriginalPath);
                await fse.move(currentPath, newOriginalFullPath, { overwrite: true });
                console.log(`   ✅ Original déplacé: ${newOriginalPath}`);

                // 3. Créer la copie de travail (~85% qualité)
                const newWorkingFullPath = path.join(UPLOAD_DIR, newWorkingPath);
                await sharp(imageBuffer)
                    .jpeg({ quality: 85, mozjpeg: true })
                    .toFile(newWorkingFullPath);

                // Créer la version WebP de la copie de travail
                const workingWebpPath = newWorkingFullPath.replace(path.extname(newWorkingFullPath), '.webp');
                await sharp(imageBuffer)
                    .webp({ quality: 80 })
                    .toFile(workingWebpPath);

                console.log(`   ✅ Copie de travail créée: ${newWorkingPath}`);

                // 4. Créer la miniature UI (~40% qualité)
                const newThumbFullPath = path.join(UPLOAD_DIR, newThumbPath);
                await sharp(imageBuffer)
                    .resize({ width: 400 })
                    .jpeg({ quality: 40, progressive: true })
                    .toFile(newThumbFullPath);

                // Créer la version WebP de la miniature
                const thumbWebpPath = newThumbFullPath.replace(path.extname(newThumbFullPath), '.webp');
                await sharp(imageBuffer)
                    .resize({ width: 400 })
                    .webp({ quality: 50 })
                    .toFile(thumbWebpPath);

                console.log(`   ✅ Miniature UI créée: ${newThumbPath}`);

                // 5. Supprimer l'ancienne miniature si elle existe et est différente
                if (currentThumbExists && currentThumbPath !== newThumbFullPath) {
                    await fse.unlink(currentThumbPath).catch(() => {});
                    const oldThumbWebpPath = currentThumbPath.replace(path.extname(currentThumbPath), '.webp');
                    await fse.unlink(oldThumbWebpPath).catch(() => {});
                    console.log(`   🗑️  Ancienne miniature supprimée`);
                }

                // 6. Mettre à jour le document dans la base de données
                await Image.updateOne(
                    { _id: image._id },
                    {
                        $set: {
                            originalPath: newOriginalPath,
                            path: newWorkingPath,
                            thumbnailPath: newThumbPath,
                            webpPath: path.relative(UPLOAD_DIR, workingWebpPath),
                            thumbnailWebpPath: path.relative(UPLOAD_DIR, thumbWebpPath)
                        }
                    }
                );

                console.log(`   ✅ Base de données mise à jour`);
                successCount++;

            } catch (error) {
                console.error(`❌ Erreur lors de la migration de ${image.originalFilename}:`, error.message);
                errors.push({
                    imageId: image._id,
                    error: error.message,
                    originalFilename: image.originalFilename
                });
                errorCount++;
            }
        }

        // Rapport final
        console.log('\n📋 RAPPORT DE MIGRATION');
        console.log('========================');
        console.log(`✅ Images migrées avec succès: ${successCount}`);
        console.log(`❌ Erreurs: ${errorCount}`);
        console.log(`📊 Taux de succès: ${((successCount / (successCount + errorCount)) * 100).toFixed(1)}%`);

        if (errors.length > 0) {
            console.log('\n❌ ERREURS DÉTAILLÉES:');
            errors.forEach((err, index) => {
                console.log(`   ${index + 1}. ${err.originalFilename}: ${err.error}`);
            });
        }

        console.log('\n🎉 Migration terminée!');

    } catch (error) {
        console.error('❌ Erreur globale lors de la migration:', error);
    }
}

async function main() {
    await connectDB();
    await migrateImages();
    await mongoose.connection.close();
    console.log('🔌 Connexion MongoDB fermée');
}

// Gestion des signaux d'interruption
process.on('SIGINT', async () => {
    console.log('\n⚠️  Interruption détectée. Fermeture propre...');
    await mongoose.connection.close();
    process.exit(0);
});

process.on('SIGTERM', async () => {
    console.log('\n⚠️  Signal de terminaison reçu. Fermeture propre...');
    await mongoose.connection.close();
    process.exit(0);
});

// Exécution du script
if (require.main === module) {
    main().catch(error => {
        console.error('💥 Erreur fatale:', error);
        process.exit(1);
    });
}

module.exports = { migrateImages };
