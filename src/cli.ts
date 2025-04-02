import readline from 'readline';
import { runWhisperOnFile, runWhisperLive } from './whisper';

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

function ask(question: string): Promise<string> {
  return new Promise(resolve => rl.question(question, resolve));
}

(async () => {
  const mode = await ask('Transcription depuis (f)ichier ou (l)ive ? ');

  if (mode.toLowerCase() === 'f') {
    const path = await ask('Chemin du fichier audio/vidéo: ');
    const text = await runWhisperOnFile(path.trim());
    console.log('\n--- Transcription ---\n');
    console.log(text);
  } else if (mode.toLowerCase() === 'l') {
    console.log('Transcription en live (Ctrl+C pour quitter)...');
    await runWhisperLive();
  } else {
    console.log('Choix invalide.');
  }
  rl.close();
})();
