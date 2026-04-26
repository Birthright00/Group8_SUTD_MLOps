import { useRef } from 'react';
import { motion } from 'framer-motion';

const UploadScreen = ({ onImageUpload }) => {
  const fileInputRef = useRef(null);

  return (
    <motion.div
      key="upload"
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      className="flex flex-col items-center justify-center min-h-[60vh]"
    >
      <input
        type="file"
        ref={fileInputRef}
        onChange={onImageUpload}
        accept="image/*"
        className="hidden"
      />

      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => fileInputRef.current?.click()}
        className="group relative overflow-hidden rounded-3xl bg-gradient-to-r from-indigo-500 to-purple-600 p-1 shadow-2xl transition-all hover:shadow-indigo-500/50"
      >
        <div className="relative rounded-3xl bg-white px-16 py-12 text-center">
          <motion.div
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 2, repeat: Infinity }}
            className="mb-6"
          >
            <svg className="mx-auto h-24 w-24 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </motion.div>
          <h2 className="text-3xl font-bold text-gray-800 mb-2">Upload Your Room</h2>
          <p className="text-gray-500">Click to select an image of your interior space</p>
        </div>
      </motion.button>

      <p className="mt-6 text-sm text-gray-400">Supports JPG, PNG • Max 10MB</p>
    </motion.div>
  );
};

export default UploadScreen;
