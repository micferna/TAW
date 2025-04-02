import sys
import json
import whisper
import argparse
import os
from datetime import timedelta
import wave
import numpy as np
import soundfile as sf
import subprocess
import tempfile
import codecs
import tqdm
import time
import threading
import traceback

# Configurer l'encodage de sortie
sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

# Variable globale pour stocker le chemin du fichier WAV temporaire à utiliser
temp_wav_to_use = None

def log_message(message):
    """Fonction pour envoyer des messages de log au serveur"""
    print(message, file=sys.stderr)
    sys.stderr.flush()

def send_progress(progress):
    """Envoie la progression du chargement du modèle"""
    print(json.dumps({"type": "modelLoadingProgress", "progress": progress}), file=sys.stderr)
    sys.stderr.flush()

class ModelLoadingObserver:
    """Classe pour surveiller le chargement du modèle et envoyer des mises à jour de progression"""
    def __init__(self, estimated_load_time=30):
        self.estimated_load_time = estimated_load_time  # temps estimé en secondes
        self.start_time = None
        self.is_loading = False
        self.thread = None
        
    def start(self):
        self.start_time = time.time()
        self.is_loading = True
        self.thread = threading.Thread(target=self._update_progress)
        self.thread.daemon = True
        self.thread.start()
    
    def stop(self):
        self.is_loading = False
        if self.thread:
            self.thread.join(timeout=1)
            
    def _update_progress(self):
        # Envoyer la progression initiale
        send_progress(0.01)
        
        while self.is_loading:
            elapsed = time.time() - self.start_time
            # Calculer la progression de façon non-linéaire pour simuler le chargement
            # Plus rapide au début, plus lent à la fin
            progress = min(0.95, elapsed / self.estimated_load_time)
            send_progress(progress)
            time.sleep(1)  # Mettre à jour chaque seconde
        
        # Progression finale
        send_progress(1.0)

def format_timestamp(seconds: float) -> str:
    """Convertit les secondes en format SRT (HH:MM:SS,mmm)"""
    return str(timedelta(seconds=seconds)).replace('.', ',')[:11]

def generate_srt(segments):
    """Génère un fichier sous-titres SRT à partir des segments de transcription"""
    srt_content = ""
    for i, segment in enumerate(segments):
        srt_content += f"{i+1}\n"
        srt_content += f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}\n"
        srt_content += f"{segment['text'].strip()}\n\n"
    return srt_content

def convert_mp3_to_wav(mp3_path):
    """Convertit un fichier MP3 en WAV pour traitement"""
    log_message(f"Début de la conversion du fichier MP3 vers WAV...")
    try:
        # Créer un fichier temporaire pour la sortie WAV
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_wav_path = temp_wav.name
        temp_wav.close()
        
        log_message(f"Fichier temporaire WAV créé: {temp_wav_path}")
        
        # Définir un timeout de 60 secondes
        timeout_seconds = 60
        
        try:
            # Méthode 1: Utiliser subprocess.run avec timeout
            log_message(f"Tentative de conversion avec FFmpeg (méthode 1)...")
            ffmpeg_cmd = ['ffmpeg', '-i', mp3_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', temp_wav_path]
            log_message(f"Commande FFmpeg: {' '.join(ffmpeg_cmd)}")
            
            # Utiliser subprocess.run avec un timeout explicite
            result = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                text=True
            )
            
            if result.returncode != 0:
                log_message(f"Erreur FFmpeg: {result.stderr}")
                raise subprocess.SubprocessError(f"FFmpeg a échoué avec le code {result.returncode}")
            
            log_message(f"Conversion FFmpeg réussie!")
            
            # Vérifier que le fichier WAV existe et n'est pas vide
            wav_size = os.path.getsize(temp_wav_path)
            log_message(f"Taille du fichier WAV généré: {wav_size} octets")
            if wav_size == 0:
                log_message(f"ERREUR: Le fichier WAV généré est vide!")
                raise ValueError("Le fichier WAV généré est vide")
                
            return temp_wav_path
            
        except subprocess.TimeoutExpired:
            log_message(f"Timeout lors de la conversion FFmpeg après {timeout_seconds} secondes.")
            log_message(f"Tentative avec méthode alternative...")
            
            # Méthode 2: Utiliser pydub si disponible
            try:
                log_message(f"Tentative de conversion avec pydub...")
                try:
                    from pydub import AudioSegment
                    log_message(f"Bibliothèque pydub importée avec succès")
                    
                    sound = AudioSegment.from_mp3(mp3_path)
                    log_message(f"Fichier MP3 chargé avec pydub. Durée: {len(sound)/1000} secondes")
                    
                    # Convertir en mono si stéréo
                    if sound.channels > 1:
                        log_message(f"Conversion stéréo vers mono...")
                        sound = sound.set_channels(1)
                    
                    # Convertir à 16kHz
                    if sound.frame_rate != 16000:
                        log_message(f"Rééchantillonnage de {sound.frame_rate}Hz à 16000Hz")
                        sound = sound.set_frame_rate(16000)
                    
                    # Exporter en WAV
                    log_message(f"Exportation vers WAV...")
                    sound.export(temp_wav_path, format="wav")
                    
                    log_message(f"Conversion pydub réussie!")
                    return temp_wav_path
                    
                except ImportError:
                    log_message(f"pydub n'est pas installé. Tentative avec soundfile...")
                    raise
                    
            except Exception as pydub_error:
                log_message(f"Erreur avec pydub: {pydub_error}")
                
                # Méthode 3: Fallback sur soundfile
                log_message(f"Tentative de conversion avec soundfile...")
                try:
                    data, samplerate = sf.read(mp3_path)
                    log_message(f"Fichier MP3 lu avec succès. Forme: {data.shape}, Sample rate: {samplerate}")
                    
                    # Convertir en mono si stéréo
                    if len(data.shape) > 1:
                        log_message(f"Conversion stéréo vers mono...")
                        data = data.mean(axis=1)
                    
                    # Rééchantillonner à 16kHz si nécessaire
                    if samplerate != 16000:
                        log_message(f"Rééchantillonnage de {samplerate}Hz à 16000Hz")
                        # Solution simple de rééchantillonnage
                        data = data[::int(samplerate/16000)]
                    
                    log_message(f"Écriture du fichier WAV avec soundfile...")
                    sf.write(temp_wav_path, data, 16000)
                    log_message(f"Fichier WAV écrit avec succès")
                    
                    # Vérifier que le fichier WAV existe et n'est pas vide
                    wav_size = os.path.getsize(temp_wav_path)
                    log_message(f"Taille du fichier WAV généré: {wav_size} octets")
                    if wav_size == 0:
                        log_message(f"ERREUR: Le fichier WAV généré est vide!")
                        raise ValueError("Le fichier WAV généré est vide")
                    
                    return temp_wav_path
                
                except Exception as sf_error:
                    log_message(f"Échec de toutes les méthodes de conversion.")
                    raise ValueError(f"Impossible de convertir le fichier MP3 après plusieurs tentatives: {sf_error}")
            
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            log_message(f"Erreur avec FFmpeg: {e}. Tentative avec soundfile...")
            
            # Alternative avec soundfile
            log_message(f"Lecture du fichier MP3 avec soundfile...")
            data, samplerate = sf.read(mp3_path)
            log_message(f"Fichier MP3 lu avec succès. Forme: {data.shape}, Sample rate: {samplerate}")
            
            # Convertir en mono si stéréo
            if len(data.shape) > 1:
                log_message(f"Conversion stéréo vers mono...")
                data = data.mean(axis=1)
            
            # Rééchantillonner à 16kHz si nécessaire
            if samplerate != 16000:
                log_message(f"Rééchantillonnage de {samplerate}Hz à 16000Hz")
                # Solution simple de rééchantillonnage
                data = data[::int(samplerate/16000)]
            
            log_message(f"Écriture du fichier WAV avec soundfile...")
            sf.write(temp_wav_path, data, 16000)
            log_message(f"Fichier WAV écrit avec succès")
            
            # Vérifier que le fichier WAV existe et n'est pas vide
            wav_size = os.path.getsize(temp_wav_path)
            log_message(f"Taille du fichier WAV généré: {wav_size} octets")
            if wav_size == 0:
                log_message(f"ERREUR: Le fichier WAV généré est vide!")
                raise ValueError("Le fichier WAV généré est vide")
                
            return temp_wav_path
            
    except Exception as e:
        log_message(f"Erreur lors de la conversion MP3 vers WAV: {e}")
        traceback.print_exc(file=sys.stderr)
        raise

def check_audio_file(file_path: str) -> bool:
    """Vérifie si le fichier audio est valide et contient des données"""
    try:
        global temp_wav_to_use  # Déplacer la déclaration global en haut de la fonction
        log_message(f"Vérification du fichier audio: {file_path}")
        
        # Vérifier si le fichier est au format MP3 ou WEBM
        if file_path.lower().endswith('.mp3'):
            log_message(f"Fichier MP3 détecté, conversion requise")
            return True  # Nous le convertirons plus tard
        elif file_path.lower().endswith('.webm'):
            log_message(f"Fichier WEBM détecté, conversion directe avec FFmpeg")
            
            # Pour les fichiers WEBM, nous utiliserons directement FFmpeg pour la conversion
            # sans essayer de réparer l'en-tête RIFF
            try:
                temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp_wav_path = temp_wav.name
                temp_wav.close()
                
                log_message(f"Fichier temporaire WAV créé pour la conversion WEBM: {temp_wav_path}")
                
                # Utiliser FFmpeg pour convertir directement le WEBM en WAV
                try:
                    ffmpeg_cmd = ['ffmpeg', '-i', file_path, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', '-y', temp_wav_path]
                    log_message(f"Commande FFmpeg pour conversion WEBM: {' '.join(ffmpeg_cmd)}")
                    
                    result = subprocess.run(
                        ffmpeg_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=30,
                        text=True
                    )
                    
                    if result.returncode != 0:
                        log_message(f"Erreur FFmpeg: {result.stderr}")
                        # Si FFmpeg échoue, nous essayons avec pydub
                        raise subprocess.SubprocessError(f"FFmpeg a échoué avec le code {result.returncode}")
                    
                    log_message(f"Conversion WEBM vers WAV réussie: {temp_wav_path}")
                    
                    # Mettre à jour le chemin du fichier à utiliser
                    temp_wav_to_use = temp_wav_path
                    return True
                    
                except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
                    log_message(f"Erreur lors de la conversion WEBM vers WAV: {e}")
                    try:
                        # Essayer avec pydub si disponible
                        from pydub import AudioSegment
                        log_message(f"Tentative de conversion avec pydub...")
                        audio = AudioSegment.from_file(file_path)
                        audio = audio.set_frame_rate(16000).set_channels(1)
                        audio.export(temp_wav_path, format="wav")
                        log_message(f"Conversion avec pydub réussie: {temp_wav_path}")
                        
                        # Mettre à jour le chemin du fichier à utiliser
                        temp_wav_to_use = temp_wav_path
                        return True
                    except Exception as pydub_error:
                        log_message(f"Échec de la conversion avec pydub: {pydub_error}")
                        return False
            except Exception as e:
                log_message(f"Erreur lors de la conversion WEBM: {e}")
                return False
        
        # Vérifier l'en-tête RIFF pour les fichiers WAV
        try:
            with open(file_path, 'rb') as f:
                header = f.read(12)  # Lire les 12 premiers octets
                if len(header) < 12:
                    log_message(f"ERREUR: Fichier trop court pour être un WAV valide")
                    return False
                
                # Vérifier l'en-tête RIFF et le format WAVE
                if header[:4] != b'RIFF' or header[8:12] != b'WAVE':
                    log_message(f"ERREUR: En-tête RIFF/WAVE manquant. Header: {header}")
                    log_message(f"Ce n'est probablement pas un fichier WAV valide")
                    
                    # Si c'est un fichier de taille raisonnable, on peut essayer de le réparer
                    file_size = os.path.getsize(file_path)
                    if file_size > 1000:  # Si le fichier a une taille raisonnable
                        log_message(f"Tentative de réparation du fichier audio...")
                        
                        # Créer un nouveau fichier WAV avec un en-tête correct
                        # Faire une copie du fichier original pour éviter les conflits d'accès
                        file_copy_path = file_path + '.copy'
                        repaired_path = file_path + '.repaired.wav'
                        
                        try:
                            # Créer une copie du fichier pour éviter les problèmes d'accès
                            with open(file_path, 'rb') as src:
                                file_data = src.read()  # Lire tout le fichier
                            
                            # Écrire les données dans le fichier de copie
                            with open(file_copy_path, 'wb') as dst:
                                dst.write(file_data)
                            
                            log_message(f"Copie du fichier créée: {file_copy_path}")
                            
                            # Maintenant, réparer le fichier à partir de la copie
                            with open(file_copy_path, 'rb') as src, open(repaired_path, 'wb') as dst:
                                # Lire toutes les données audio brutes
                                data = src.read()
                                
                                # Écrire un en-tête WAV valide
                                # Format: PCM 16 bits, mono, 16000 Hz
                                sample_rate = 16000
                                channels = 1
                                bits_per_sample = 16
                                
                                # Calculer les valeurs pour l'en-tête
                                data_size = len(data)
                                header_size = 36 + 8  # Taille standard + sous-bloc data
                                file_size = header_size + data_size
                                byte_rate = sample_rate * channels * bits_per_sample // 8
                                block_align = channels * bits_per_sample // 8
                                
                                # Écrire l'en-tête RIFF
                                dst.write(b'RIFF')
                                dst.write((file_size - 8).to_bytes(4, byteorder='little'))
                                dst.write(b'WAVE')
                                
                                # Écrire le sous-bloc fmt
                                dst.write(b'fmt ')
                                dst.write((16).to_bytes(4, byteorder='little'))  # Taille du sous-bloc fmt
                                dst.write((1).to_bytes(2, byteorder='little'))  # Format PCM = 1
                                dst.write((channels).to_bytes(2, byteorder='little'))
                                dst.write((sample_rate).to_bytes(4, byteorder='little'))
                                dst.write((byte_rate).to_bytes(4, byteorder='little'))
                                dst.write((block_align).to_bytes(2, byteorder='little'))
                                dst.write((bits_per_sample).to_bytes(2, byteorder='little'))
                                
                                # Écrire le sous-bloc data
                                dst.write(b'data')
                                dst.write((data_size).to_bytes(4, byteorder='little'))
                                
                                # Écrire les données audio
                                dst.write(data)
                            
                            log_message(f"Fichier réparé créé: {repaired_path}")
                            log_message(f"Utilisation du fichier réparé pour la transcription")
                            
                            # Utiliser le fichier réparé pour la transcription
                            temp_wav_to_use = repaired_path
                            
                            # Nettoyer le fichier de copie
                            try:
                                os.remove(file_copy_path)
                                log_message(f"Fichier de copie supprimé: {file_copy_path}")
                            except Exception as cleanup_error:
                                log_message(f"Erreur lors de la suppression du fichier de copie: {cleanup_error}")
                            
                            return True
                        except Exception as repair_error:
                            log_message(f"Échec de la réparation du fichier: {repair_error}")
                            return False
                    else:
                        log_message(f"Fichier trop petit pour être réparé")
                        return False
        except Exception as header_error:
            log_message(f"Erreur lors de la vérification de l'en-tête: {header_error}")
            # Continuer avec les autres méthodes de vérification
        
        # Pour les fichiers WAV
        try:
            # Tenter d'utiliser soundfile qui prend en charge plusieurs formats
            log_message(f"Tentative de lecture du fichier avec soundfile...")
            data, samplerate = sf.read(file_path)
            log_message(f"Lecture réussie! Paramètres du fichier audio:")
            log_message(f"- Taux d'échantillonnage: {samplerate} Hz")
            log_message(f"- Forme du signal: {data.shape}")
            
            # Vérifier si le signal contient du son (non silencieux)
            if len(data) > 0:
                max_amplitude = np.max(np.abs(data))
                log_message(f"Signal audio valide - Amplitude max: {max_amplitude}")
                if max_amplitude < 0.01:
                    log_message(f"ATTENTION: Signal très faible, possible silence")
                return True
            else:
                log_message(f"ERREUR: Le fichier audio ne contient pas de données")
                return False
                
        except Exception as sf_error:
            log_message(f"Erreur lors de la lecture avec soundfile: {sf_error}")
            try:
                # Fallback sur wave pour les fichiers WAV
                log_message(f"Tentative de lecture avec le module wave...")
                with wave.open(file_path, 'rb') as wav_file:
                    params = wav_file.getparams()
                    log_message(f"Paramètres du fichier WAV:")
                    log_message(f"- Canaux: {params.nchannels}")
                    log_message(f"- Largeur d'échantillon: {params.sampwidth}")
                    log_message(f"- Taux d'échantillonnage: {params.framerate}")
                    log_message(f"- Nombre de frames: {params.nframes}")
                    
                    # Vérifier si le fichier contient des données
                    if params.nframes > 0:
                        log_message(f"Fichier WAV valide - {params.nframes} frames")
                        return True
                    else:
                        log_message(f"ERREUR: Le fichier WAV ne contient pas de frames")
                        return False
            except Exception as wave_error:
                log_message(f"Erreur lors de la lecture avec wave: {wave_error}")
                return False
    except Exception as e:
        log_message(f"Erreur générale lors de la vérification du fichier audio: {e}")
        traceback.print_exc(file=sys.stderr)
        return False

def main():
    try:
        log_message("==== Démarrage du script de transcription Whisper ====")
        log_message(f"Version Python: {sys.version}")
        log_message(f"Arguments sys.argv: {sys.argv}")
        
        parser = argparse.ArgumentParser(description="Transcription audio avec Whisper")
        parser.add_argument("audio_file", help="Chemin vers le fichier audio à transcrire")
        parser.add_argument("--generate-srt", action="store_true", help="Générer des sous-titres SRT")
        parser.add_argument("--model", choices=["tiny", "base", "small", "medium", "large"], default="medium", 
                          help="Modèle Whisper à utiliser (défaut: medium)")
        args = parser.parse_args()
        
        log_message(f"Arguments reçus: {args}")
        
        # Normaliser le chemin du fichier
        audio_path = os.path.abspath(os.path.normpath(args.audio_file))
        log_message(f"Chemin absolu normalisé reçu: {audio_path}")
        
        # Vérifier si le fichier existe
        if not os.path.isfile(audio_path):
            log_message(f"ERREUR: Fichier non trouvé: {audio_path}")
            sys.exit(1)
        else:
            log_message(f"SUCCES: Fichier trouvé à l'emplacement: {audio_path}")
            log_message(f"Taille du fichier: {os.path.getsize(audio_path)} octets")
        
        # Réinitialiser la variable globale
        global temp_wav_to_use
        temp_wav_to_use = None
        
        # Vérifier le fichier audio
        if not check_audio_file(audio_path):
            log_message(f"ERREUR: Le fichier audio n'est pas valide ou ne contient pas de données")
            sys.exit(1)
        
        # Utiliser le fichier converti si disponible
        file_to_transcribe = audio_path
        if temp_wav_to_use is not None:
            log_message(f"Utilisation du fichier audio converti/réparé: {temp_wav_to_use}")
            file_to_transcribe = temp_wav_to_use
        # Sinon, convertir le fichier MP3 en WAV si nécessaire
        elif audio_path.lower().endswith('.mp3'):
            log_message(f"Conversion du fichier MP3 en WAV...")
            file_to_transcribe = convert_mp3_to_wav(audio_path)
            log_message(f"Conversion terminée. Fichier WAV: {file_to_transcribe}")
            log_message(f"Taille du fichier WAV: {os.path.getsize(file_to_transcribe)} octets")
        
        log_message(f"Fichier à transcrire : {file_to_transcribe}")
        
        # Charger le modèle Whisper avec un observateur de progression
        model_name = args.model
        log_message(f"Chargement du modèle Whisper '{model_name}'...")
        observer = ModelLoadingObserver(estimated_load_time=20)  # 20 secondes estimées pour le chargement
        observer.start()
        
        # S'assurer que le chargement du modèle commence réellement
        log_message(f"Tentative de chargement du modèle '{model_name}'...")
        try:
            model = whisper.load_model(model_name, device="cpu")
            log_message("Modèle chargé avec succès")
        except Exception as e:
            log_message(f"Erreur lors du chargement du modèle '{model_name}': {e}")
            if model_name != "base":
                # Si le modèle demandé n'est pas 'base', on essaie avec 'base' comme fallback
                log_message(f"Tentative avec le modèle 'base' comme alternative...")
                try:
                    model = whisper.load_model("base", device="cpu")
                    log_message("Modèle 'base' chargé avec succès")
                except Exception as e2:
                    log_message(f"Erreur lors du chargement du modèle 'base': {e2}")
                    traceback.print_exc(file=sys.stderr)
                    observer.stop()
                    sys.exit(1)
            else:
                traceback.print_exc(file=sys.stderr)
                observer.stop()
                sys.exit(1)
            
        observer.stop()  # Arrêter l'observateur une fois le modèle chargé
        log_message("Modèle chargé avec succès")
        
        # Transcrire l'audio
        log_message("Début de la transcription...")
        try:
            result = model.transcribe(
                file_to_transcribe,
                language="fr",
                task="transcribe",
                fp16=False,
                verbose=True,
                no_speech_threshold=0.6,
                logprob_threshold=-1.0,
                compression_ratio_threshold=1.2,
                temperature=0.0,
                best_of=5,
                beam_size=5,
                word_timestamps=True,
                initial_prompt="Ceci est un enregistrement audio à transcrire fidèlement en français."
            )
            log_message("Transcription terminée avec succès")
        except Exception as e:
            log_message(f"Erreur pendant la transcription: {e}")
            traceback.print_exc(file=sys.stderr)
            
            # Nettoyer les fichiers temporaires avant de quitter
            if temp_wav_to_use is not None and temp_wav_to_use != audio_path:
                try:
                    os.remove(temp_wav_to_use)
                    log_message(f"Fichier temporaire supprimé: {temp_wav_to_use}")
                except Exception as cleanup_error:
                    log_message(f"Erreur lors de la suppression du fichier temporaire: {cleanup_error}")
            
            sys.exit(1)
        
        # Vérifier si le texte transcrit est vide
        if not result["text"].strip():
            log_message("ATTENTION: Aucun texte détecté dans l'audio")
            # Remplacer par un message explicite
            result["text"] = "[Aucune parole détectée dans l'enregistrement]"
        else:
            log_message(f"Texte transcrit (premiers 100 caractères): {result['text'][:100]}...")
        
        # Format de sortie spécial pour faciliter la lecture
        log_message("Préparation du résultat...")
        print("DÉBUT_TEXTE_TRANSCRIPTION")
        print(result["text"])
        print("FIN_TEXTE_TRANSCRIPTION")
        
        # Générer les sous-titres SRT si demandé
        if args.generate_srt and "segments" in result:
            log_message("Génération des sous-titres SRT...")
            srt_content = generate_srt(result["segments"])
            print("DÉBUT_SRT")
            print(srt_content)
            print("FIN_SRT")
            log_message("Sous-titres SRT générés")
        
        log_message("Script terminé avec succès")
        
        # Nettoyer les fichiers temporaires avant de quitter
        if temp_wav_to_use is not None and temp_wav_to_use != audio_path:
            try:
                os.remove(temp_wav_to_use)
                log_message(f"Fichier temporaire supprimé: {temp_wav_to_use}")
            except Exception as cleanup_error:
                log_message(f"Erreur lors de la suppression du fichier temporaire: {cleanup_error}")
        
        return 0
    except Exception as e:
        log_message(f"Exception non gérée: {e}")
        traceback.print_exc(file=sys.stderr)
        return 1

if __name__ == "__main__":
    main() 