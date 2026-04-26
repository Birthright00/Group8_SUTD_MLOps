import { motion } from 'framer-motion';

const ExpertCritique = ({ critique }) => {
  if (!critique) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.8 }}
      className="bg-white rounded-2xl shadow-xl p-8"
    >
      <div className="flex items-start gap-4">
        <div className="flex-shrink-0">
          <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center">
            <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          </div>
        </div>
        <div className="flex-1">
          <h3 className="text-2xl font-bold text-gray-800 mb-3">Expert Analysis 💬</h3>
          <p className="text-gray-700 leading-relaxed whitespace-pre-line">{critique}</p>
        </div>
      </div>
    </motion.div>
  );
};

export default ExpertCritique;
