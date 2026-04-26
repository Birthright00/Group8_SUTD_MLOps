import { getAnalyzeUrl, getChatUrl, getEditImageUrl, getCompletePipelineUrl } from '../config.js';

/**
 * Convert a File object to base64 string
 */
const fileToBase64 = (file) => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // Remove the data:image/...;base64, prefix
      const base64 = reader.result.split(',')[1];
      resolve(base64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
};

/**
 * Fetch with custom timeout
 * Browsers don't support fetch timeout natively, this adds it
 */
const fetchWithTimeout = async (url, options = {}, timeoutMs = 1200000) => {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return response;
  } catch (error) {
    clearTimeout(timeout);
    if (error.name === 'AbortError') {
      throw new Error('Request timed out after 40 minutes. Sequential multi-object editing is long (~10-20 min typical, plus up to 6 min cold start). Check Modal logs to see where it stopped.');
    }
    throw error;
  }
};

/**
 * Analyze an image with the vision model
 * Returns: {
 *   vision_analysis, edit_suggestions, polished_prompts, fill_prompts,
 *   design_review, edited_images
 * }
 * fill_prompts is what FLUX was fed (chatbot polish ∪ raw VLM fallback).
 */
export const analyzeImage = async (imageFile, prompt) => {
  try {
    console.log('🚀 [Frontend] Starting image analysis...');
    console.log('📝 [Frontend] Prompt:', prompt);
    console.log('🖼️ [Frontend] Image file:', imageFile.name, imageFile.size, 'bytes');

    // Convert image to base64
    const base64Image = await fileToBase64(imageFile);
    console.log('✅ [Frontend] Converted to base64:', base64Image.length, 'chars');

    // Call Modal endpoint. Timeout must cover: cold start (up to ~6 min) +
    // VLM + chatbot polish (~1-2 min) + sequential FLUX editing
    // (INPAINT_CFG.iterations_per_object * num_objects * ~20s per pass).
    const url = getAnalyzeUrl();
    console.log('🌐 [Frontend] Calling endpoint:', url);
    console.log('⏰ [Frontend] Timeout set to 40 minutes');

    const response = await fetchWithTimeout(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: base64Image,
        prompt: prompt,
        generate_images: true,  // Enable image generation
        edit_objects: []  // Will be filled after we get suggestions
      }),
    }, 2400000); // 40 minutes — matches proxy_server.py and modal_updated_complete.py ceilings

    console.log('📡 [Frontend] Response status:', response.status);

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Failed to analyze image' }));
      console.error('❌ [Frontend] Response not OK:', error);
      throw new Error(error.error || `Server error: ${response.status}`);
    }

    const data = await response.json();
    console.log('📦 [Frontend] RAW RESPONSE:', JSON.stringify(data, null, 2));
    console.log('📦 [Frontend] Received data:', {
      hasVisionAnalysis: !!data.vision_analysis,
      objectCount: Object.keys(data.vision_analysis?.objects || {}).length,
      suggestionCount: Object.keys(data.edit_suggestions || {}).length,
      polishedCount: Object.keys(data.polished_prompts || {}).length,
      hasDesignReview: !!data.design_review?.review_markdown,
      hasEditedImage: !!data.edited_image,
      editedImageSize: data.edited_image ? data.edited_image.length : 0,
    });

    // Response shape (see modal_updated_complete.py -> complete_pipeline docstring):
    //   {
    //     vision_analysis:  { objects, ... },
    //     edit_suggestions: { obj: raw_vlm_prompt },        // VLM first pass
    //     polished_prompts: { obj: chatbot_enriched },      // parser hits only
    //     fill_prompts:     { obj: prompt_used_for_flux },  // merged with fallback
    //     design_review:    { review_markdown, ... },
    //     edited_images: {
    //       object_order:         [ ... ],
    //       object_intermediates: { obj: base64 },
    //       iteration_details:    { obj: [iter1, iter2, ...] },
    //       final:                "<base64_png>",
    //     },
    //   }
    const editedImagesData = data.edited_images || {};
    console.log('[Frontend] editedImagesData:', editedImagesData);
    console.log('[Frontend] editedImagesData keys:', Object.keys(editedImagesData));

    const objectIntermediates = editedImagesData.object_intermediates || {};
    const iterationDetails = editedImagesData.iteration_details || {};
    const finalImage = editedImagesData.final || null;
    const objectOrder = editedImagesData.object_order || [];

    console.log('[Frontend] objectIntermediates:', Object.keys(objectIntermediates));
    console.log('[Frontend] iterationDetails:', Object.keys(iterationDetails));
    console.log('[Frontend] objectOrder from backend:', objectOrder);
    console.log('[Frontend] finalImage exists:', !!finalImage);

    const result = {
      objects: data.vision_analysis?.objects || {},
      rawOutput: data.vision_analysis?.raw_output || '',
      // VLM first-pass suggestions (what the vision model drafted).
      editSuggestions: data.edit_suggestions || {},
      // Chatbot-polished per-object prompts (parser hits only — may be sparser than editSuggestions).
      polishedPrompts: data.polished_prompts || {},
      // What FLUX actually consumed: polished where available, VLM draft as fallback.
      fillPrompts: data.fill_prompts || {},
      // Full structured critique from the fine-tuned designer chatbot.
      chatbotCritique: data.design_review?.review_markdown || '',
      // Final transformed image
      editedImage: finalImage,
      // Sequential object transformations (cumulative)
      objectIntermediates: objectIntermediates,
      // Refinement iterations for each object
      iterationDetails: iterationDetails,
      // Explicit ordering from backend (guarantees editing sequence)
      objectOrder: objectOrder,
    };

    console.log('[Frontend] Final result:', {
      hasEditedImage: !!result.editedImage,
      objectCount: Object.keys(result.objectIntermediates).length,
      iterationDetailsCount: Object.keys(result.iterationDetails).length
    });

    console.log('✅ [Frontend] Analysis complete!', {
      hasEditedImage: !!result.editedImage,
      editedImageLength: result.editedImage?.length
    });

    return result;
  } catch (error) {
    console.error('❌ [Frontend] API Error:', error);
    throw new Error(error.message || 'Failed to analyze image');
  }
};

/**
 * Ask the chatbot a question
 */
export const askChatbot = async (question, maxTokens = 512) => {
  try {
    const response = await fetch(getChatUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        question: question,
        max_new_tokens: maxTokens,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Failed to get response' }));
      throw new Error(error.error || `Server error: ${response.status}`);
    }

    const data = await response.json();
    return data.response;
  } catch (error) {
    console.error('Chat API Error:', error);
    throw new Error(error.message || 'Failed to get chatbot response');
  }
};

/**
 * Edit a specific object in an image
 */
export const editImage = async (imageFile, targetObject, fillPrompt, iterations = 3) => {
  try {
    const base64Image = await fileToBase64(imageFile);

    const response = await fetch(getEditImageUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: base64Image,
        target_object: targetObject,
        fill_prompt: fillPrompt,
        iterations: iterations,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Failed to edit image' }));
      throw new Error(error.error || `Server error: ${response.status}`);
    }

    const data = await response.json();
    return data.image; // Returns base64 encoded image
  } catch (error) {
    console.error('Edit Image API Error:', error);
    throw new Error(error.message || 'Failed to edit image');
  }
};

/**
 * Complete pipeline: analyze + generate edited images
 */
export const completePipeline = async (imageFile, prompt, objectsToEdit = [], generateImages = false) => {
  try {
    const base64Image = await fileToBase64(imageFile);

    const response = await fetch(getCompletePipelineUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: base64Image,
        prompt: prompt,
        edit_objects: objectsToEdit,
        generate_images: generateImages,
      }),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Failed to process pipeline' }));
      throw new Error(error.error || `Server error: ${response.status}`);
    }

    const data = await response.json();

    return {
      objects: data.vision_analysis?.objects || {},
      rawOutput: data.vision_analysis?.raw_output || '',
      editSuggestions: data.edit_suggestions || {},
      chatbotCritique: data.chatbot_critique || '',
      editedImages: data.edited_images || {}, // Object mapping object_name -> base64 image
    };
  } catch (error) {
    console.error('Complete Pipeline API Error:', error);
    throw new Error(error.message || 'Failed to process complete pipeline');
  }
};

/**
 * Check API health (basic connectivity test)
 */
export const checkHealth = async () => {
  try {
    // Try to reach the chat endpoint with a simple request
    const response = await fetch(getChatUrl(), {
      method: 'OPTIONS',
    });
    return { status: response.ok ? 'healthy' : 'unhealthy' };
  } catch (error) {
    return { status: 'unhealthy', error: error.message };
  }
};
