import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import { promises as fs } from 'fs';
import { EventEmitter } from 'events';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Créer un EventEmitter pour la progression
const progressEmitter = new EventEmitter();

export async function transcribeAudio(
    audioPath: string, 
    generateSrt: boolean = false,
    model: 'tiny' | 'base' | 'small' | 'medium' | 'large' = 'base'
): Promise<{ text: string; srt?: string }> {
    // Vérifier si le fichier existe avant de lancer la transcription
    try {
        await fs.access(audioPath);
        console.log('Fichier audio trouvé:', audioPath);
        
        // Vérifier la taille du fichier
        const stats = await fs.stat(audioPath);
        console.log('Taille du fichier:', stats.size, 'octets');
        
        if (stats.size === 0) {
            throw new Error('Le fichier audio est vide');
        }
    } catch (error) {
        console.error('Erreur lors de la vérification du fichier:', error);
        throw new Error(`Le fichier audio '${audioPath}' n'existe pas ou n'est pas accessible`);
    }

    return new Promise((resolve, reject) => {
        const pythonScript = path.join(__dirname, '..', 'whisper_transcribe.py');
        const args = [pythonScript, audioPath];
        
        if (generateSrt) {
            args.push('--generate-srt');
        }
        
        // Ajouter le paramètre du modèle
        args.push('--model', model);

        console.log('Chemin du script Python:', pythonScript);
        console.log('Chemin du fichier audio:', audioPath);
        console.log(`Modèle Whisper utilisé: ${model}`);
        console.log('Lancement de la transcription avec les arguments:', args);

        // Configurer un timeout de 5 minutes pour la transcription
        const timeoutId = setTimeout(() => {
            console.error('⏱️ Timeout de transcription dépassé (5 minutes)');
            if (pythonProcess.pid) {
                console.log(`🛑 Tentative d'arrêt du processus Python (PID: ${pythonProcess.pid})`);
                try {
                    // Tenter de tuer le processus Python
                    process.kill(pythonProcess.pid);
                } catch (e) {
                    console.error(`❌ Erreur lors de l'arrêt du processus:`, e);
                }
            }
            reject(new Error('Timeout de transcription dépassé (5 minutes)'));
        }, 5 * 60 * 1000); // 5 minutes en millisecondes

        const pythonProcess = spawn('python', args);
        let transcriptionResult = '';
        let srtContent = '';
        let lastProgressTime = Date.now();

        console.log(`🚀 Processus Python démarré avec PID: ${pythonProcess.pid}`);
        
        // Émettre un événement avec le PID pour permettre l'annulation
        if (pythonProcess.pid) {
          progressEmitter.emit('processStarted', pythonProcess.pid);
        }

        pythonProcess.stdout.on('data', (data) => {
            const message = data.toString().trim();
            console.log('Message Python stdout:', message);
            lastProgressTime = Date.now(); // Mettre à jour le temps de la dernière activité
            
            // Chercher le texte entre les balises spéciales
            const transcriptionMatch = message.match(/DÉBUT_TEXTE_TRANSCRIPTION\n([\s\S]*?)\nFIN_TEXTE_TRANSCRIPTION/);
            if (transcriptionMatch && transcriptionMatch[1]) {
                transcriptionResult = transcriptionMatch[1].trim();
                console.log('Texte de transcription extrait des balises:', transcriptionResult);
            }
            
            try {
                const jsonData = JSON.parse(message);
                if (jsonData.text) {
                    transcriptionResult = jsonData.text;
                    console.log('Texte de transcription reçu via JSON:', transcriptionResult);
                }
                if (jsonData.srt) {
                    srtContent = jsonData.srt;
                }
            } catch (e) {
                // Pas un JSON, déjà traité ci-dessus
            }
        });

        pythonProcess.stderr.on('data', (data) => {
            const message = data.toString().trim();
            console.log('Message Python stderr:', message);
            lastProgressTime = Date.now(); // Mettre à jour le temps de la dernière activité
            
            try {
                const jsonData = JSON.parse(message);
                if (jsonData.type === 'modelLoadingProgress') {
                    // Émettre la progression via l'EventEmitter
                    progressEmitter.emit('modelLoadingProgress', { progress: jsonData.progress });
                }
            } catch (e) {
                // Message non-JSON
                if (message.includes('Conversion') || message.includes('transcription')) {
                    // C'est un message de progression normal
                    console.log(`📋 Progression: ${message}`);
                }
            }
        });

        // Vérifier périodiquement si le processus est bloqué (pas d'activité pendant 30 secondes)
        const activityCheckInterval = setInterval(() => {
            const inactiveTime = Date.now() - lastProgressTime;
            if (inactiveTime > 30000) { // 30 secondes
                console.warn(`⚠️ Aucune activité depuis ${Math.round(inactiveTime/1000)} secondes`);
            }
        }, 10000); // Vérifier toutes les 10 secondes

        pythonProcess.on('close', (code) => {
            clearTimeout(timeoutId); // Annuler le timeout
            clearInterval(activityCheckInterval); // Arrêter la vérification d'activité
            console.log('Processus Python terminé avec le code:', code);
            if (code === 0) {
                console.log('Résultat final de la transcription:', transcriptionResult);
                resolve({
                    text: transcriptionResult || '',
                    ...(srtContent && { srt: srtContent })
                });
            } else {
                reject(new Error(`Le processus Python s'est terminé avec le code ${code}`));
            }
        });

        pythonProcess.on('error', (error) => {
            clearTimeout(timeoutId); // Annuler le timeout
            clearInterval(activityCheckInterval); // Arrêter la vérification d'activité
            console.error('Erreur lors du lancement du processus Python:', error);
            reject(error);
        });
    });
}

export async function runWhisperLive(): Promise<void> {
  return new Promise((resolve, reject) => {
    const python = spawn('python3', ['whisper.py', '--live']);
    python.stdout?.on('data', (data: Buffer) => process.stdout.write(data.toString('utf8')));
    python.stderr?.on('data', (err: Buffer) => console.error('[Whisper error]', err.toString('utf8')));
    python.on('close', () => resolve());
  });
}

// Exporter l'EventEmitter pour que le serveur puisse l'utiliser
export { progressEmitter };
