document.addEventListener('DOMContentLoaded', () => {
    const startRecording = document.getElementById('start-recording');
    const stopRecording = document.getElementById('stop-recording');
    const liveTranscription = document.getElementById('live-transcription');
    const testMicrophone = document.getElementById('test-microphone');
    const microphoneIndicator = document.getElementById('microphone-indicator');

    // Test du microphone
    testMicrophone.addEventListener('click', async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            microphoneIndicator.classList.remove('hidden');
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const source = audioContext.createMediaStreamSource(stream);
            const analyser = audioContext.createAnalyser();
            source.connect(analyser);
            analyser.fftSize = 256;
            const bufferLength = analyser.frequencyBinCount;
            const dataArray = new Uint8Array(bufferLength);

            const checkMicrophone = () => {
                analyser.getByteFrequencyData(dataArray);
                const sum = dataArray.reduce((a, b) => a + b, 0);
                if (sum > 0) {
                    microphoneIndicator.textContent = 'Microphone actif et captant le son...';
                } else {
                    microphoneIndicator.textContent = 'Microphone actif mais aucun son détecté.';
                }
                requestAnimationFrame(checkMicrophone);
            };
            checkMicrophone();
        } catch (error) {
            console.error('Erreur lors de l\'accès au microphone:', error);
            alert('Impossible d\'accéder au microphone. Veuillez vérifier les permissions.');
        }
    });

    // Autres logiques existantes...
}); 