import { motion } from 'framer-motion';
import StyleSelector from './StyleSelector';

const PreviewScreen = ({
  selectedImage,
  selectedStyle,
  customPrompt,
  error,
  onStyleSelect,
  onCustomPromptChange,
  onReset,
  onSubmit,
}) => {
  return (
    <motion.div
      key="preview"
      initial={{ opacity: 0, x: 100 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -100 }}
      className="space-y-8"
    >
      {/* Image Preview */}
      <div className="relative rounded-2xl overflow-hidden shadow-2xl max-w-3xl mx-auto">
        <img
          src={selectedImage}
          alt="Selected room"
          className="w-full h-auto"
        />
        <button
          onClick={onReset}
          className="absolute top-4 right-4 bg-white/90 hover:bg-white rounded-full p-2 shadow-lg transition-all"
        >
          <svg className="w-6 h-6 text-gray-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Style Selection */}
      <StyleSelector
        selectedStyle={selectedStyle}
        onStyleSelect={onStyleSelect}
        customPrompt={customPrompt}
        onCustomPromptChange={onCustomPromptChange}
      />

      {/* Error Message */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 max-w-4xl mx-auto"
        >
          {error}
        </motion.div>
      )}

      {/* Submit Button */}
      <div className="max-w-4xl mx-auto">
        <motion.button
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          onClick={onSubmit}
          disabled={!selectedStyle && !customPrompt}
          className="w-full bg-gradient-to-r from-indigo-500 to-purple-600 text-white py-4 rounded-xl font-semibold text-lg shadow-xl hover:shadow-2xl disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          Transform My Space ✨
        </motion.button>
      </div>
    </motion.div>
  );
};

export default PreviewScreen;
