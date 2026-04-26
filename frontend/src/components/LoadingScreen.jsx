import { motion } from 'framer-motion';

const LoadingScreen = () => {
  return (
    <motion.div
      key="loading"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex flex-col items-center justify-center min-h-[60vh]"
    >
      <div className="bg-white rounded-3xl shadow-2xl p-12 max-w-md text-center">
        {/* Animated Icon */}
        <div className="flex justify-center mb-8">
          <motion.div
            animate={{
              scale: [1, 1.2, 1],
            }}
            transition={{
              scale: { duration: 1, repeat: Infinity },
            }}
          >
            <div className="w-20 h-20 rounded-full bg-gradient-to-r from-indigo-500 to-purple-600 flex items-center justify-center">
              <svg className="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
              </svg>
            </div>
          </motion.div>
        </div>

        <h2 className="text-2xl font-bold text-gray-800 mb-4">Designing Your Space</h2>

        {/* Loading Steps */}
        <div className="space-y-3 text-left mb-6">
          {['Analyzing current layout...', 'Generating design ideas...', 'Creating expert recommendations...'].map((text, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.8 }}
              className="flex items-center gap-3 text-gray-600"
            >
              <motion.div
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 1, repeat: Infinity, delay: i * 0.8 }}
                className="w-2 h-2 rounded-full bg-indigo-500"
              />
              {text}
            </motion.div>
          ))}
        </div>

        <p className="text-sm text-gray-400">
          First time: 15-20 minutes (3 objects × 10 iterations + cold start)
          <br />
          After warm-up: 8-12 minutes
          <br />
          <span className="text-xs text-gray-500">Please be patient - multi-object editing takes time!</span>
        </p>
      </div>
    </motion.div>
  );
};

export default LoadingScreen;
