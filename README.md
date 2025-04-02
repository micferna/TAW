# Whisper Transcription App

Application web de transcription audio utilisant le modèle OpenAI Whisper pour une transcription précise et efficace en français.

![Interface de l'application](./Capture%20d%27%C3%A9cran%202025-04-02%20080819.png)

## Fonctionnalités

- **Transcription de fichiers audio** (MP3, WAV, WEBM)
- **Enregistrement et transcription en direct** via le microphone
- **Génération de sous-titres SRT**
- **Interface moderne** avec thème sombre et interface réactive
- **Visualisation audio** en temps réel pendant l'enregistrement
- **Utilisation flexible des modèles Whisper** (tiny, base, small, medium, large)
- **API disponible** pour une intégration dans d'autres applications

## Installation

### Prérequis

- Node.js (v16 ou supérieur)
- Python 3.8+ avec pip
- FFmpeg installé et accessible dans le PATH

### Étapes d'installation

1. **Cloner le dépôt**
```bash
git clone https://github.com/micferna/TAW.git
cd whisper-transcription-app
```

2. **Installer les dépendances Node.js**
```bash
npm install
```

3. **Installer les dépendances Python**
```bash
pip install openai-whisper soundfile numpy pydub
```

4. **Lancer l'application**
```bash
npm run dev
```

5. **Accéder à l'application**
Ouvrez votre navigateur à l'adresse: http://localhost:3000

## Utilisation

### Interface Web

1. **Transcription de fichier**
   - Cliquez sur "Choisir un fichier" pour sélectionner votre fichier audio
   - Cochez l'option "Générer des sous-titres SRT" si nécessaire
   - Cliquez sur "Transcrire"
   - Téléchargez le résultat en format TXT ou SRT

2. **Transcription en direct**
   - Cliquez sur "Démarrer l'enregistrement"
   - Parlez clairement dans votre microphone
   - Cliquez sur "Arrêter l'enregistrement" pour lancer la transcription
   - La transcription s'affiche automatiquement

### Utilisation API

#### REST API pour les fichiers

```bash
curl -X POST -F "audio=@/chemin/vers/votre/fichier.mp3" -F "generateSrt=true" http://localhost:3000/transcribe
```

#### WebSocket pour l'audio en direct

```javascript
const socket = io('http://localhost:3000');

// Envoyer des données audio
socket.emit('audioData', audioArrayBuffer);

// Recevoir le résultat
socket.on('transcription', (data) => {
  console.log(data.text);
});
```

#### Script Python direct

Vous pouvez aussi utiliser directement le script Python :

```bash
python whisper_transcribe.py chemin/vers/audio.mp3 --model tiny --generate-srt
```

## Configuration des modèles

L'application utilise différents modèles Whisper selon les besoins :

- **tiny** : Modèle le plus léger et rapide, idéal pour l'enregistrement en direct
- **base** : Bon équilibre entre précision et vitesse
- **small** : Meilleure précision, mais plus lent
- **medium** : Haute précision pour les fichiers importants
- **large** : Précision maximale, mais très lourd et lent

## Personnalisation

Vous pouvez modifier les paramètres du modèle Whisper dans le fichier `whisper_transcribe.py` :

```python
result = model.transcribe(
    file_to_transcribe,
    language="fr",  # Changer la langue ici
    no_speech_threshold=0.6,
    logprob_threshold=-1.0,
    compression_ratio_threshold=1.2,
    temperature=0.0,
    best_of=5,
    beam_size=5,
    word_timestamps=True,
    initial_prompt="Ceci est un enregistrement audio à transcrire fidèlement en français."
)
```

## Licence

Ce projet est sous licence MIT.

## Remerciements

- [OpenAI Whisper](https://github.com/openai/whisper) pour le modèle de transcription
- [Socket.IO](https://socket.io/) pour la communication en temps réel
- [Tailwind CSS](https://tailwindcss.com/) pour le design de l'interface 