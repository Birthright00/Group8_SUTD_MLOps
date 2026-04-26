import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { analyzeImage } from './utils/api';
import UploadScreen from './components/UploadScreen';
import PreviewScreen from './components/PreviewScreen';
import LoadingScreen from './components/LoadingScreen';
import ResultsScreen from './components/ResultsScreen';

function App() {
  const [step, setStep] = useState('upload'); // 'upload', 'preview', 'loading', 'results'
  const [selectedImage, setSelectedImage] = useState(null);
  const [imageFile, setImageFile] = useState(null);
  const [selectedStyle, setSelectedStyle] = useState(null);
  const [customPrompt, setCustomPrompt] = useState('');
  const [results, setResults] = useState(null);
  const [error, setError] = useState(null);

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      setImageFile(file);
      const reader = new FileReader();
      reader.onload = (e) => {
        setSelectedImage(e.target.result);
        setStep('preview');
      };
      reader.readAsDataURL(file);
    }
  };

  const handleStyleSelect = (style) => {
    setSelectedStyle(style);
    setCustomPrompt('');
  };

  const handleCustomPromptChange = (e) => {
    setCustomPrompt(e.target.value);
    setSelectedStyle(null);
  };

  const handleSubmit = async () => {
    if (!imageFile || (!selectedStyle && !customPrompt)) return;

    setStep('loading');
    setError(null);

    try {
      const prompt = customPrompt || `${selectedStyle.name} themed interior design`;
      const data = await analyzeImage(imageFile, prompt);

      // Debug logging for object ordering
      if (data.objectOrder) {
        console.log('[Frontend] Received object_order from backend:', data.objectOrder);
      }
      if (data.iterationDetails) {
        console.log('[Frontend] iterationDetails keys:', Object.keys(data.iterationDetails));
      }

      setResults(data);
      setStep('results');
    } catch (err) {
      setError(err.message);
      setStep('preview');
    }
  };

  const handleReset = () => {
    setStep('upload');
    setSelectedImage(null);
    setImageFile(null);
    setSelectedStyle(null);
    setCustomPrompt('');
    setResults(null);
    setError(null);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-12"
        >
          <h1 className="text-5xl font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent mb-2">
            Interior AI Designer
          </h1>
          <p className="text-gray-600">Transform your space with AI-powered design</p>
        </motion.div>

        <AnimatePresence mode="wait">
          {step === 'upload' && <UploadScreen onImageUpload={handleImageUpload} />}

          {step === 'preview' && (
            <PreviewScreen
              selectedImage={selectedImage}
              selectedStyle={selectedStyle}
              customPrompt={customPrompt}
              error={error}
              onStyleSelect={handleStyleSelect}
              onCustomPromptChange={handleCustomPromptChange}
              onReset={handleReset}
              onSubmit={handleSubmit}
            />
          )}

          {step === 'loading' && <LoadingScreen />}

          {step === 'results' && results && (
            <ResultsScreen results={results} selectedImage={selectedImage} onReset={handleReset} />
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

export default App;
