import { motion } from 'framer-motion';

const DESIGN_STYLES = [
  { id: 'japanese', name: 'Japanese', emoji: '🏯', description: 'Zen and minimalist' },
  { id: 'victorian', name: 'Victorian', emoji: '👑', description: 'Elegant and ornate' },
  { id: 'modern', name: 'Modern', emoji: '✨', description: 'Clean and contemporary' },
  { id: 'scandinavian', name: 'Scandinavian', emoji: '🌲', description: 'Simple and cozy' },
  { id: 'industrial', name: 'Industrial', emoji: '🏭', description: 'Raw and edgy' },
  { id: 'bohemian', name: 'Bohemian', emoji: '🌺', description: 'Eclectic and colorful' },
];

const StyleSelector = ({ selectedStyle, onStyleSelect, customPrompt, onCustomPromptChange }) => {
  return (
    <div className="max-w-4xl mx-auto">
      <h3 className="text-2xl font-bold text-gray-800 mb-6 text-center">Choose Your Style</h3>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
        {DESIGN_STYLES.map((style, index) => (
          <motion.button
            key={style.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.1 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => onStyleSelect(style)}
            className={`relative rounded-xl p-6 text-left transition-all ${
              selectedStyle?.id === style.id
                ? 'bg-gradient-to-br from-indigo-500 to-purple-600 text-white shadow-xl ring-4 ring-indigo-300'
                : 'bg-white hover:bg-gray-50 text-gray-800 shadow-md'
            }`}
          >
            <div className="text-4xl mb-2">{style.emoji}</div>
            <div className="font-semibold text-lg">{style.name}</div>
            <div className={`text-sm ${selectedStyle?.id === style.id ? 'text-white/80' : 'text-gray-500'}`}>
              {style.description}
            </div>
          </motion.button>
        ))}
      </div>

      {/* Custom Prompt */}
      <div className="mb-8">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Or describe your own style:
        </label>
        <input
          type="text"
          value={customPrompt}
          onChange={onCustomPromptChange}
          placeholder="e.g., Cozy rustic farmhouse with warm colors..."
          className="w-full px-4 py-3 rounded-xl border-2 border-gray-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-100 outline-none transition-all"
        />
      </div>
    </div>
  );
};

export { DESIGN_STYLES };
export default StyleSelector;
