import { motion } from 'framer-motion';
import TransformationCarousel from './TransformationCarousel';
import IterationCarousel from './IterationCarousel';
import ObjectsTable from './ObjectsTable';
import SuggestionsTable from './SuggestionsTable';

const ResultsScreen = ({ results, selectedImage, onReset }) => {
  const handleDownloadAll = () => {
    Object.entries(results.objectIntermediates).forEach(([obj, img]) => {
      const link = document.createElement('a');
      link.href = `data:image/png;base64,${img}`;
      link.download = `${obj}-transformed.png`;
      link.click();
    });
  };

  return (
    <motion.div
      key="results"
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="space-y-8 pb-12"
    >
      {/* Success Header */}
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: 'spring', duration: 0.5 }}
        className="text-center"
      >
        <div className="inline-block bg-green-100 rounded-full p-4 mb-4">
          <svg className="w-12 h-12 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h2 className="text-3xl font-bold text-gray-800">Your Design is Ready!</h2>
      </motion.div>

      {/* Original Image */}
      <motion.div initial={{ opacity: 0, x: -50 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.2 }}>
        <h3 className="text-xl font-semibold text-gray-700 mb-3">Original Space</h3>
        <div className="rounded-2xl overflow-hidden shadow-xl">
          <img src={selectedImage} alt="Original" className="w-full" />
        </div>
      </motion.div>

      {/* Sequential Object Transformations */}
      {results.objectIntermediates && Object.keys(results.objectIntermediates).length > 0 ? (
        <motion.div
          initial={{ opacity: 0, x: 50 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
          className="space-y-8"
        >
          {/* Sequential Progression Carousel */}
          <TransformationCarousel
            objectIntermediates={results.objectIntermediates}
            objectOrder={results.objectOrder}
          />

          {/* Refinement Iterations per Object */}
          {results.iterationDetails && Object.keys(results.iterationDetails).length > 0 && (
            <IterationCarousel iterationDetails={results.iterationDetails} objectOrder={results.objectOrder} />
          )}

          {/* Download Button */}
          <div className="flex justify-center gap-4 mt-6">
            <button
              onClick={handleDownloadAll}
              className="bg-indigo-600 hover:bg-indigo-700 text-white px-6 py-2 rounded-lg font-medium transition-colors"
            >
              Download All Transformations
            </button>
          </div>
        </motion.div>
      ) : results.editedImage ? (
        // Fallback: Show single final image if no iterations data
        <motion.div initial={{ opacity: 0, x: 50 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.3 }}>
          <div className="flex items-center gap-2 mb-3">
            <h3 className="text-xl font-semibold text-gray-700">Transformed Space</h3>
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-indigo-500 to-purple-600 text-white">
              AI Generated ✨
            </span>
          </div>
          <div className="rounded-2xl overflow-hidden shadow-xl ring-4 ring-indigo-200">
            <img src={`data:image/png;base64,${results.editedImage}`} alt="Transformed" className="w-full" />
          </div>
          <p className="mt-2 text-sm text-gray-500 text-center">Edited based on your selected design style</p>
        </motion.div>
      ) : null}

      {/* Table 1: Current Items Viewed */}
      <ObjectsTable objects={results.objects} />

      {/* Table 2: Suggested Edits — VLM draft side-by-side with chatbot polish */}
      <SuggestionsTable
        objects={results.objects}
        editSuggestions={results.editSuggestions}
        polishedPrompts={results.polishedPrompts}
      />

      {/* Try Another Button */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1 }} className="text-center">
        <button
          onClick={onReset}
          className="bg-gradient-to-r from-indigo-500 to-purple-600 text-white px-8 py-4 rounded-xl font-semibold text-lg shadow-xl hover:shadow-2xl transition-all hover:scale-105"
        >
          Transform Another Space 🎨
        </button>
      </motion.div>
    </motion.div>
  );
};

export default ResultsScreen;
