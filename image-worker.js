const { parentPort } = require('worker_threads');
const sharp = require('sharp');
const fse = require('fs-extra');
const path = require('path');

parentPort.on('message', async (task) => {
    const { tempPath, originalStoragePath, workingCopyPath, thumbPath, thumbSize } = task;

    try {
        const imageBuffer = await fse.readFile(tempPath);
        const imageProcessor = sharp(imageBuffer);
        const metadata = await imageProcessor.metadata();

        // 1. Déplacer le fichier original (rapide, pas de ré-encodage)
        await fse.move(tempPath, originalStoragePath, { overwrite: true });

        // 2. Créer la copie de travail (~85% qualité) et sa version WebP
        const workingCopyPromise = sharp(imageBuffer)
            .jpeg({ quality: 85, mozjpeg: true })
            .toFile(workingCopyPath);

        const workingCopyWebpPromise = sharp(imageBuffer)
            .webp({ quality: 80 })
            .toFile(workingCopyPath.replace(path.extname(workingCopyPath), '.webp'));

        // 3. Créer la miniature UI (~40% qualité) et sa version WebP
        const thumbnailPromise = sharp(imageBuffer)
            .resize({ width: 400 }) // Redimensionner avant de compresser
            .jpeg({ quality: 40, progressive: true })
            .toFile(thumbPath);

        const thumbnailWebpPromise = sharp(imageBuffer)
            .resize({ width: 400 })
            .webp({ quality: 50 })
            .toFile(thumbPath.replace(path.extname(thumbPath), '.webp'));

        // Exécuter toutes les créations en parallèle
        await Promise.all([
            workingCopyPromise,
            workingCopyWebpPromise,
            thumbnailPromise,
            thumbnailWebpPromise
        ]);

        parentPort.postMessage({
            status: 'success',
            originalStoragePath,
            workingCopyPath,
            thumbPath,
            width: metadata.width,
            height: metadata.height,
            originalTempPath: tempPath // Renvoyer pour faire le lien
        });

    } catch (error) {
        console.error(`[Worker] Erreur lors du traitement de ${tempPath}:`, error);
        parentPort.postMessage({ status: 'error', message: error.message, originalTempPath: tempPath });
        await fse.unlink(tempPath).catch(() => {});
    }
});
