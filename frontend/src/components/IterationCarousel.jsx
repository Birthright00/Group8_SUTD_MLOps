import { useState, useEffect } from 'react';

const IterationCarousel = ({ iterationDetails, objectOrder }) => {
  const [currentObjectForIterations, setCurrentObjectForIterations] = useState(null);
  const [currentIterationIndex, setCurrentIterationIndex] = useState(0);

  const iterationEntries = (objectOrder || Object.keys(iterationDetails)).map(obj => [
    obj,
    iterationDetails[obj],
  ]);

  // Initialize current object
  useEffect(() => {
    if (!currentObjectForIterations && iterationEntries.length > 0) {
      setCurrentObjectForIterations(iterationEntries[0][0]);
    }
  }, [iterationEntries, currentObjectForIterations]);

  const currentIterations = currentObjectForIterations ? iterationDetails[currentObjectForIterations] : [];

  return (
    <div className="mt-8">
      <h3 className="text-xl font-bold text-gray-800 mb-4">Refinement Passes</h3>
      <p className="text-gray-600 mb-6">View individual refinement iterations for each object</p>

      <div className="bg-gray-50 rounded-xl p-6">
        {/* Object Selector */}
        <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
          {iterationEntries.map(([objName]) => (
            <button
              key={objName}
              onClick={() => {
                setCurrentObjectForIterations(objName);
                setCurrentIterationIndex(0);
              }}
              className={`px-4 py-2 rounded-lg font-medium capitalize whitespace-nowrap transition-all ${
                objName === currentObjectForIterations
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-100'
              }`}
            >
              {objName}
            </button>
          ))}
        </div>

        {/* Iteration Carousel */}
        {currentIterations && currentIterations.length > 0 && (
          <div className="relative">
            <div className="rounded-xl overflow-hidden shadow-lg relative">
              <img
                src={`data:image/png;base64,${currentIterations[currentIterationIndex]}`}
                alt={`${currentObjectForIterations} iteration ${currentIterationIndex + 1}`}
                className="w-full"
              />

              {/* Iteration Info */}
              <div className="absolute top-4 left-4 bg-black/70 text-white px-4 py-2 rounded-lg">
                <div className="text-sm font-semibold capitalize">
                  {currentObjectForIterations} - Refinement {currentIterationIndex + 1}
                </div>
                <div className="text-xs text-gray-300">
                  Pass {currentIterationIndex + 1} of {currentIterations.length}
                </div>
              </div>

              {/* Navigation Arrows */}
              {currentIterations.length > 1 && (
                <>
                  <button
                    onClick={() => setCurrentIterationIndex(Math.max(0, currentIterationIndex - 1))}
                    disabled={currentIterationIndex === 0}
                    className="absolute left-4 top-1/2 -translate-y-1/2 w-12 h-12 bg-black/50 hover:bg-black/70 text-white rounded-full flex items-center justify-center disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                  <button
                    onClick={() =>
                      setCurrentIterationIndex(Math.min(currentIterations.length - 1, currentIterationIndex + 1))
                    }
                    disabled={currentIterationIndex === currentIterations.length - 1}
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
              {currentIterations.map((_, idx) => (
                <button
                  key={idx}
                  onClick={() => setCurrentIterationIndex(idx)}
                  className={`h-2 rounded-full transition-all ${
                    idx === currentIterationIndex ? 'w-8 bg-indigo-600' : 'w-2 bg-gray-300 hover:bg-gray-400'
                  }`}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default IterationCarousel;
