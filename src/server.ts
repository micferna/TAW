// --- src/server.ts ---
import express, { Request, Response } from 'express';
import formidable, { File, Fields } from 'formidable';
import dotenv from 'dotenv';
import { transcribeAudio, progressEmitter } from './whisper.js';
import path from 'path';
import { promises as fs } from 'fs';
import http from 'http';
import { Server } from 'socket.io';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config();
const app = express();
const server = http.createServer(app);
const io = new Server(server);
const port = process.env.PORT || 3001;

// Middleware pour servir les fichiers statiques
app.use(express.static(path.join(__dirname, '../public')));

// Route pour la transcription
app.post('/transcribe', async (req: Request, res: Response) => {
  console.log(`🔽 Réception d'une demande de transcription de fichier`);
  const uploadDir = path.join(__dirname, '../uploads');
  
  // Créer le dossier uploads s'il n'existe pas
  try {
    await fs.access(uploadDir);
  } catch {
    console.log(`📁 Création du dossier uploads`);
    await fs.mkdir(uploadDir, { recursive: true });
  }

  console.log(`⏳ Configuration de formidable...`);
  const form = formidable({ 
    multiples: false,
    uploadDir,
    keepExtensions: true,
    maxFileSize: 100 * 1024 * 1024 // Augmenter à 100 MB
  });

  console.log(`⏳ Traitement du formulaire en cours...`);
  form.parse(req, async (err: Error | null, fields: Fields, files: formidable.Files) => {
    if (err) {
      console.error('❌ Erreur lors de l\'upload:', err);
      return res.status(500).json({ error: 'Erreur lors de l\'upload: ' + err.message });
    }

    console.log(`📦 Contenu de files:`, Object.keys(files));
    console.log(`📦 Contenu de fields:`, Object.keys(fields));

    const audioFiles = files.audio;
    if (!audioFiles) {
      console.error('❌ Fichier audio manquant');
      return res.status(400).json({ error: 'Fichier audio manquant' });
    }

    // Gérer le cas où audioFiles est un tableau (multiple=true)
    let audioFile: File;
    if (Array.isArray(audioFiles)) {
      console.log(`ℹ️ Plusieurs fichiers audio reçus, utilisation du premier`);
      if (audioFiles.length === 0) {
        console.error('❌ Aucun fichier audio reçu dans le tableau');
        return res.status(400).json({ error: 'Aucun fichier audio reçu' });
      }
      audioFile = audioFiles[0] as unknown as File;
    } else {
      audioFile = audioFiles as unknown as File;
    }

    if (!audioFile.filepath) {
      console.error('❌ Fichier audio sans chemin');
      return res.status(400).json({ error: 'Fichier audio invalide: pas de chemin' });
    }

    try {
      // Vérifier que le fichier existe
      try {
        await fs.access(audioFile.filepath);
        console.log(`✅ Fichier accessible: ${audioFile.filepath}`);
      } catch (e) {
        console.error(`❌ Impossible d'accéder au fichier: ${audioFile.filepath}`, e);
        return res.status(500).json({ error: 'Fichier inaccessible après upload' });
      }

      console.log(`📄 Fichier reçu: ${audioFile.filepath}`);
      console.log(`🔤 Type de fichier: ${audioFile.mimetype}`);
      console.log(`📏 Taille du fichier: ${audioFile.size} octets`);

      // Vérifier que le fichier a une taille non nulle
      if (audioFile.size === 0) {
        console.error('❌ Fichier vide');
        return res.status(400).json({ error: 'Le fichier audio est vide' });
      }

      console.log(`🔄 Début du traitement du fichier`);

      // Traiter le fichier MP3 si nécessaire
      let fileToTranscribe = audioFile.filepath;
      
      const generateSrt = fields.generateSrt?.[0] === 'true';
      console.log(`🔤 Option de génération SRT: ${generateSrt ? 'Oui' : 'Non'}`);
      
      // Choisir le modèle en fonction de l'extension du fichier
      // Pour les MP3, utiliser un modèle plus petit et plus rapide
      let model: 'tiny' | 'base' | 'small' | 'medium' | 'large' = 'base';
      
      if (audioFile.filepath.toLowerCase().endsWith('.mp3')) {
        console.log(`📊 Fichier MP3 détecté, utilisation du modèle 'tiny' pour plus de rapidité`);
        model = 'tiny';
      } else {
        const requestedModel = fields.model?.[0] as 'tiny' | 'base' | 'small' | 'medium' | 'large';
        if (requestedModel && ['tiny', 'base', 'small', 'medium', 'large'].includes(requestedModel)) {
          model = requestedModel;
          console.log(`📊 Modèle spécifié par l'utilisateur: '${model}'`);
        } else {
          console.log(`📊 Modèle par défaut utilisé: '${model}'`);
        }
      }
      
      console.log(`🎯 Lancement de la transcription avec Whisper...`);
      const result = await transcribeAudio(fileToTranscribe, generateSrt, model);
      
      console.log(`✅ Transcription réussie! Longueur du texte: ${result.text?.length || 0} caractères`);
      
      // Envoyer le résultat au client sous forme de JSON standard
      res.json(result);
      
      // Nettoyer le fichier temporaire après la transcription
      try {
        await fs.unlink(audioFile.filepath);
        console.log(`🧹 Fichier temporaire supprimé: ${audioFile.filepath}`);
      } catch (error) {
        console.error('❌ Erreur lors de la suppression du fichier temporaire:', error);
      }
    } catch (error) {
      console.error('❌ Erreur lors de la transcription:', error);
      
      // Envoyer l'erreur au client
      res.status(500).json({ 
        error: error instanceof Error ? error.message : 'Erreur pendant la transcription' 
      });
      
      // Nettoyer le fichier temporaire en cas d'erreur
      try {
        if (audioFile.filepath) {
          await fs.unlink(audioFile.filepath);
          console.log(`🧹 Fichier temporaire supprimé après erreur: ${audioFile.filepath}`);
        }
      } catch (unlinkError) {
        console.error('❌ Erreur lors de la suppression du fichier temporaire:', unlinkError);
      }
    }
  });
});

// Gestion des connexions WebSocket
io.on('connection', (socket) => {
  console.log(`👤 Nouvelle connexion client (ID: ${socket.id})`);

  // Variables pour suivre le processus Python actif pour ce client
  let activeProcess: number | null = null;

  // Écouter les événements de progression
  const progressHandler = (data: { progress: number }) => {
    console.log(`📊 Progression du modèle: ${Math.round(data.progress * 100)}%`);
    socket.emit('modelLoadingProgress', data);
  };

  progressEmitter.on('modelLoadingProgress', progressHandler);

  socket.on('startRecording', () => {
    console.log(`🎙️ Démarrage de l'enregistrement (client: ${socket.id})`);
  });

  socket.on('cancelTranscription', () => {
    console.log(`🛑 Annulation de la transcription demandée (client: ${socket.id})`);
    if (activeProcess) {
      try {
        process.kill(activeProcess);
        console.log(`✅ Processus Python arrêté (PID: ${activeProcess})`);
      } catch (error) {
        console.error(`❌ Erreur lors de l'arrêt du processus (PID: ${activeProcess}):`, error);
      }
      activeProcess = null;
    }
  });

  socket.on('audioData', async (audioData) => {
    try {
      const tempFilePath = path.join(__dirname, '../uploads', `temp-${Date.now()}.wav`);
      console.log(`💾 Réception de données audio (client: ${socket.id})`);
      console.log(`📝 Écriture du fichier temporaire: ${tempFilePath}`);
      
      // Vérifier que les données sont soit un Buffer soit un ArrayBuffer
      let audioBuffer;
      if (audioData instanceof ArrayBuffer) {
        audioBuffer = Buffer.from(audioData);
      } else if (Buffer.isBuffer(audioData)) {
        audioBuffer = audioData;
      } else {
        audioBuffer = Buffer.from(audioData);
      }
      
      console.log(`📊 Taille des données audio reçues: ${audioBuffer.length} octets`);
      
      // Vérifier la présence de l'en-tête RIFF
      const hasRiffHeader = audioBuffer.length >= 44 && 
                            audioBuffer.slice(0, 4).toString() === 'RIFF' && 
                            audioBuffer.slice(8, 12).toString() === 'WAVE';
      
      if (!hasRiffHeader) {
        console.warn("⚠️ Avertissement: L'audio ne contient pas d'en-tête RIFF valide");
      } else {
        console.log("✅ En-tête RIFF détecté dans les données audio");
      }
      
      await fs.writeFile(tempFilePath, audioBuffer);
      console.log(`✅ Fichier temporaire créé et accessible: ${tempFilePath}`);

      console.log(`🎯 Démarrage de la transcription...`);
      
      // Surveiller le processus Python pour pouvoir l'arrêter
      const processStartHandler = (pid: number) => {
        activeProcess = pid;
        console.log(`📋 Processus Python assigné au client ${socket.id} (PID: ${pid})`);
      };
      
      progressEmitter.once('processStarted', processStartHandler);
      
      // Utiliser le modèle tiny pour l'enregistrement en direct (plus rapide)
      const model = 'tiny'; // Plus léger et plus rapide pour le direct
      console.log(`📊 Utilisation du modèle '${model}' pour l'enregistrement en direct`);
      
      const result = await transcribeAudio(tempFilePath, false, model);
      
      // Nettoyage
      activeProcess = null;
      progressEmitter.off('processStarted', processStartHandler);
      
      console.log(`✅ Transcription réussie! Longueur du texte: ${result.text?.length || 0} caractères`);
      
      if (result.text) {
        socket.emit('transcription', { text: result.text });
        console.log(`📤 Résultat envoyé au client: "${result.text.substring(0, 50)}${result.text.length > 50 ? '...' : ''}"`);
      } else {
        console.log(`⚠️ Aucun texte de transcription reçu`);
        socket.emit('error', 'Aucun texte de transcription reçu');
      }
      
      await fs.unlink(tempFilePath);
      console.log(`🧹 Fichier temporaire supprimé: ${tempFilePath}`);
    } catch (error: any) {
      activeProcess = null;
      console.error(`❌ Erreur lors de la transcription en direct:`, error);
      socket.emit('error', error?.message || 'Erreur lors de la transcription');
    }
  });

  socket.on('rawAudioData', async (audioData) => {
    try {
      console.log(`💾 Réception de données audio brutes (client: ${socket.id})`);
      
      // Créer un nom de fichier temporaire unique avec l'extension appropriée
      const tempFilePath = path.join(__dirname, '../uploads', `temp-${Date.now()}.webm`);
      console.log(`📝 Écriture du fichier temporaire WEBM: ${tempFilePath}`);
      
      // Conversion en Buffer si nécessaire
      let audioBuffer;
      if (audioData instanceof ArrayBuffer) {
        audioBuffer = Buffer.from(audioData);
      } else if (Buffer.isBuffer(audioData)) {
        audioBuffer = audioData;
      } else {
        audioBuffer = Buffer.from(audioData);
      }
      
      console.log(`📊 Taille des données audio reçues: ${audioBuffer.length} octets`);
      
      // Écrire le fichier webm directement
      await fs.writeFile(tempFilePath, audioBuffer);
      console.log(`✅ Fichier WEBM créé: ${tempFilePath}`);
      
      // Surveiller le processus Python pour pouvoir l'arrêter
      const processStartHandler = (pid: number) => {
        activeProcess = pid;
        console.log(`📋 Processus Python assigné au client ${socket.id} (PID: ${pid})`);
      };
      
      progressEmitter.once('processStarted', processStartHandler);
      
      // Utiliser le modèle tiny pour l'enregistrement en direct
      const model = 'tiny';
      console.log(`📊 Utilisation du modèle '${model}' pour l'enregistrement en direct`);
      
      // Transcription directe du fichier webm
      const result = await transcribeAudio(tempFilePath, false, model);
      
      // Nettoyage
      activeProcess = null;
      progressEmitter.off('processStarted', processStartHandler);
      
      console.log(`✅ Transcription réussie! Longueur du texte: ${result.text?.length || 0} caractères`);
      
      if (result.text) {
        socket.emit('transcription', { text: result.text });
        console.log(`📤 Résultat envoyé au client: "${result.text.substring(0, 50)}${result.text.length > 50 ? '...' : ''}"`);
      } else {
        console.log(`⚠️ Aucun texte de transcription reçu`);
        socket.emit('error', 'Aucun texte de transcription reçu');
      }
      
      // Nettoyer le fichier temporaire
      await fs.unlink(tempFilePath);
      console.log(`🧹 Fichier temporaire supprimé: ${tempFilePath}`);
      
    } catch (error: any) {
      activeProcess = null;
      console.error(`❌ Erreur lors de la transcription en direct:`, error);
      socket.emit('error', error?.message || 'Erreur lors de la transcription');
    }
  });

  socket.on('stopRecording', () => {
    console.log(`⏹️ Arrêt de l'enregistrement (client: ${socket.id})`);
  });

  socket.on('disconnect', () => {
    console.log(`👋 Déconnexion client (ID: ${socket.id})`);
    // Nettoyer l'écouteur d'événements lors de la déconnexion
    progressEmitter.off('modelLoadingProgress', progressHandler);
    
    // Arrêter le processus en cours si le client se déconnecte
    if (activeProcess) {
      try {
        process.kill(activeProcess);
        console.log(`✅ Processus Python arrêté après déconnexion (PID: ${activeProcess})`);
      } catch (error) {
        console.error(`❌ Erreur lors de l'arrêt du processus:`, error);
      }
      activeProcess = null;
    }
  });
});

// Démarrage du serveur
server.listen(port, () => {
  console.log(`✨ Serveur lancé sur http://localhost:${port}`);
  console.log(`📊 Interface disponible à cette adresse`);
  console.log(`💡 En attente d'activité...`);
  console.log(`ℹ️ Les logs suivants montreront les actions des utilisateurs`);
  console.log(`------------------------------------------`);
});

// Ajouter une vérification périodique d'activité
setInterval(() => {
  console.log(`💓 Serveur actif - ${new Date().toLocaleTimeString()} - En attente d'activité...`);
}, 60000); // Afficher un message toutes les minutes