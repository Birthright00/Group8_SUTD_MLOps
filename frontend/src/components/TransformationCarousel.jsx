import { useState } from 'react';

const TransformationCarousel = ({ objectIntermediates, objectOrder }) => {
  const [currentTransformIndex, setCurrentTransformIndex] = useState(0);

  const transformEntries = (objectOrder || Object.keys(objectIntermediates)).map(obj => [
    obj,
    objectIntermediates[obj],
  ]);
  const [currentObjName, currentImage] = transformEntries[currentTransformIndex] || [];

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-2xl font-bold text-gray-800">Transformed Space</h3>
        <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-gradient-to-r from-indigo-500 to-purple-600 text-white">
          Sequential Editing
        </span>
      </div>
      <p className="text-gray-600 mb-6">Navigate through transformation passes using arrows</p>

      <div className="relative">
        {/* Main Image Display */}
        <div className="rounded-2xl overflow-hidden shadow-xl relative">
          <img
            src={`data:image/png;base64,${currentImage}`}
            alt={`After editing ${currentObjName}`}
            className="w-full"
          />

          {/* Image Info Overlay */}
          <div className="absolute top-4 left-4 bg-black/70 text-white px-4 py-2 rounded-lg">
            <div className="text-sm font-semibold capitalize">
              Pass {currentTransformIndex + 1}: {currentObjName}
            </div>
            <div className="text-xs text-gray-300">After editing {currentObjName}</div>
          </div>

          {/* Navigation Arrows */}
          {transformEntries.length > 1 && (
            <>
              <button
                onClick={() => setCurrentTransformIndex(Math.max(0, currentTransformIndex - 1))}
                disabled={currentTransformIndex === 0}
                className="absolute left-4 top-1/2 -translate-y-1/2 w-12 h-12 bg-black/50 hover:bg-black/70 text-white rounded-full flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <button
                onClick={() =>
                  setCurrentTransformIndex(Math.min(transformEntries.length - 1, currentTransformIndex + 1))
                }
                disabled={currentTransformIndex === transformEntries.length - 1}
                className="absolute right-4 top-1/2 -translate-y-1/2 w-12 h-12 bg-black/50 hover:bg-black/70 text-white rounded-full flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </>
          )}
        </div>

        {/* Progress Indicator */}
        <div className="flex items-center justify-center gap-2 mt-4">
          {transformEntries.map((_, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentTransformIndex(idx)}
              className={`h-2 rounded-full transition-all ${
                idx === currentTransformIndex ? 'w-8 bg-indigo-600' : 'w-2 bg-gray-300 hover:bg-gray-400'
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
};

export default TransformationCarousel;
