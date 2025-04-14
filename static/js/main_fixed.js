document.addEventListener('DOMContentLoaded', function() {
    // Form elements
    const crawlForm = document.getElementById('crawl-form');
    const queryForm = document.getElementById('query-form');
    
    // Buttons
    const crawlBtn = document.getElementById('crawl-btn');
    const processBtn = document.getElementById('process-btn');
    const queryBtn = document.getElementById('query-btn');
    const statusLink = document.getElementById('status-link');
    
    // Status and result containers
    const crawlStatus = document.getElementById('crawl-status');
    const crawlResults = document.getElementById('crawl-results');
    const crawlResultsMessage = document.getElementById('crawl-results-message');
    const sampleUrlsList = document.getElementById('sample-urls-list');
    
    const embeddingStatus = document.getElementById('embedding-status');
    const embeddingMessage = document.getElementById('embedding-message');
    const embeddingProgressBar = document.getElementById('embedding-progress-bar');
    const embeddingResults = document.getElementById('embedding-results');
    const embeddingResultsMessage = document.getElementById('embedding-results-message');
    const noEmbeddingsMessage = document.getElementById('no-embeddings-message');
    
    const queryStatus = document.getElementById('query-status');
    const queryResults = document.getElementById('query-results');
    const answerText = document.getElementById('answer-text');
    const sourcesList = document.getElementById('sources-list');
    
    // Modal elements
    const statusModal = new bootstrap.Modal(document.getElementById('status-modal'));
    
    // Variables to track state
    let totalUrlsToProcess = 0;
    let processedUrls = 0;
    
    // Initialize by loading database status
    loadDatabaseStatus();
    
    // Event listeners
    crawlForm.addEventListener('submit', function(e) {
        e.preventDefault();
        startCrawling();
    });
    
    processBtn.addEventListener('click', function() {
        startProcessing();
    });
    
    queryForm.addEventListener('submit', function(e) {
        e.preventDefault();
        submitQuery();
    });
    
    statusLink.addEventListener('click', function(e) {
        e.preventDefault();
        showStatusModal();
    });
    
    // Function to start crawling process
    function startCrawling() {
        const baseUrl = document.getElementById('base-url').value;
        
        if (!baseUrl) {
            alert('Please enter a valid URL');
            return;
        }
        
        // Show crawling status
        crawlBtn.disabled = true;
        crawlStatus.classList.remove('d-none');
        crawlResults.classList.add('d-none');
        
        // Make API request to start crawling
        fetch('/api/crawl', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ base_url: baseUrl })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Crawling failed: ' + response.statusText);
            }
            return response.json();
        })
        .then(data => {
            crawlStatus.classList.add('d-none');
            crawlResults.classList.remove('d-none');
            
            // Update the results display
            crawlResultsMessage.textContent = data.message;
            
            // Store the total URLs for progress tracking
            totalUrlsToProcess = data.url_count;
            
            // Display sample URLs
            sampleUrlsList.innerHTML = '';
            if (data.sample_urls && data.sample_urls.length > 0) {
                data.sample_urls.forEach(url => {
                    const li = document.createElement('li');
                    li.textContent = url;
                    sampleUrlsList.appendChild(li);
                });
            } else {
                const li = document.createElement('li');
                li.textContent = 'No URLs found';
                sampleUrlsList.appendChild(li);
            }
            
            crawlBtn.disabled = false;
        })
        .catch(error => {
            console.error('Error:', error);
            crawlStatus.classList.add('d-none');
            alert('Error during crawling: ' + error.message);
            crawlBtn.disabled = false;
        });
    }
    
    // Function to start processing/embedding documents
    function startProcessing() {
        processBtn.disabled = true;
        processedUrls = 0;
        
        // Show embedding status
        embeddingStatus.classList.remove('d-none');
        embeddingResults.classList.add('d-none');
        noEmbeddingsMessage.classList.add('d-none');
        
        // If no URLs were crawled, we'll use sample URLs and set a total
        if (totalUrlsToProcess === 0) {
            totalUrlsToProcess = 5;  // Sample URLs count
        }
        
        // Update progress bar
        updateProgressBar(0);
        
        // Start the processing in batches
        processNextBatch();
    }
    
    // Function to process the next batch of URLs
        // Function to process the next batch of URLs
        function processNextBatch() {
            // // Define sample URLs (in case user didn't crawl first) - Not needed here, handled by backend now
            // const sampleUrls = [ ... ];
    
            fetch('/api/process', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                // The backend now handles using session or samples, so send empty body if not manual
                body: JSON.stringify({}) 
            })
            .then(response => {
                if (!response.ok) {
                     // Try to get error message from backend if possible
                     return response.json().then(err => { throw new Error(err.error || `Processing failed: ${response.status} ${response.statusText}`) });
                }
                return response.json();
            })
            .then(data => {
                // --- CORRECTED LOGIC ---
                // Update processed count using the correct field from the response
                const countFromBatch = data.processed_in_batch; // Use the correct key
                
                // Ensure it's a number, default to 0 if missing/invalid
                const validCount = (typeof countFromBatch === 'number' && !isNaN(countFromBatch)) ? countFromBatch : 0;
                processedUrls += validCount; 
                
                // Update progress (use totalUrlsToProcess if available, otherwise estimate based on batch size?)
                // Need to ensure totalUrlsToProcess was set correctly by crawl step or a default
                let progress = 0;
                let progressText = '';
                if (totalUrlsToProcess > 0) {
                     progress = Math.min(100, Math.round((processedUrls / totalUrlsToProcess) * 100));
                     progressText = `Processing documents: ${processedUrls}/${totalUrlsToProcess} (${progress}%)`;
                } else {
                     // If totalUrlsToProcess wasn't set (e.g., user clicked Process without Crawl), 
                     // the progress bar might not be accurate. Show cumulative count.
                     progressText = `Processing documents... Batch processed ${validCount}. Total processed: ${processedUrls}`;
                     // Maybe set progress to 100 if data.remaining is 0?
                     if(data.remaining_in_session === 0) progress = 100; 
                }
               
                updateProgressBar(progress);
                embeddingMessage.textContent = progressText; // Update message
                
                // If there are more URLs to process (check the correct key from response)
                // Use remaining_in_session as defined in your updated app.py response
                if (data.remaining_in_session > 0) { 
                    // Continue with next batch after a short delay
                    setTimeout(processNextBatch, 1000); 
                } else {
                    // Processing complete (either finished session or was manual/sample)
                    embeddingStatus.classList.add('d-none');
                    embeddingResults.classList.remove('d-none');
                    
                    // Use the final cumulative count for the message
                    embeddingResultsMessage.textContent = `Successfully processed ${processedUrls} documents.`; 
                    
                    processBtn.disabled = false;
                    totalUrlsToProcess = 0; // Reset for next potential crawl
                    processedUrls = 0; // Reset counter
                    
                    // Refresh database status
                    loadDatabaseStatus();
                }
                // --- END CORRECTED LOGIC ---
            })
            .catch(error => {
                console.error('Error during processing batch:', error);
                embeddingStatus.classList.add('d-none');
                embeddingResults.classList.remove('d-none'); // Show results area even on error
                embeddingResultsMessage.textContent = 'Error during processing: ' + error.message; // Show error message
                processBtn.disabled = false;
                 totalUrlsToProcess = 0; // Reset 
                 processedUrls = 0; 
            });
        }
    
    // Function to update progress bar
    function updateProgressBar(percentage) {
        embeddingProgressBar.style.width = `${percentage}%`;
        embeddingProgressBar.setAttribute('aria-valuenow', percentage);
    }
    
    // Function to submit a query
    function submitQuery() {
        const queryText = document.getElementById('query-text').value;
        
        if (!queryText) {
            alert('Please enter a question');
            return;
        }
        
        // Show querying status
        queryBtn.disabled = true;
        queryStatus.classList.remove('d-none');
        queryResults.classList.add('d-none');
        
        // Make API request to query the system
        fetch('/api/query', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query: queryText })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Query failed: ' + response.statusText);
            }
            return response.json();
        })
        .then(data => {
            queryStatus.classList.add('d-none');
            queryResults.classList.remove('d-none');
            
            // Format the answer with code blocks
            answerText.innerHTML = formatAnswerText(data.answer);
            
            // Display sources
            displaySources(data.sources);
            
            queryBtn.disabled = false;
        })
        .catch(error => {
            console.error('Error:', error);
            queryStatus.classList.add('d-none');
            alert('Error processing query: ' + error.message);
            queryBtn.disabled = false;
        });
    }
    
    // Function to format answer text with code blocks and line breaks
    function formatAnswerText(text) {
        if (!text) return '';
        
        // Replace markdown code blocks with HTML
        let formatted = text.replace(/```(\w*)([\s\S]*?)```/g, '<pre class="bg-dark p-3 rounded"><code>$2</code></pre>');
        
        // Replace inline code
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // Replace newlines with <br>
        formatted = formatted.replace(/\n/g, '<br>');
        
        return formatted;
    }
    
    // Function to display sources
    function displaySources(sources) {
        sourcesList.innerHTML = '';
        
        if (!sources || sources.length === 0) {
            const li = document.createElement('li');
            li.className = 'list-group-item';
            li.textContent = 'No sources available';
            sourcesList.appendChild(li);
            return;
        }
        
        sources.forEach(source => {
            const li = document.createElement('li');
            li.className = 'list-group-item';
            
            const link = document.createElement('a');
            link.href = source.url;
            link.textContent = source.title || source.url;
            link.target = '_blank';
            link.className = 'text-primary';
            
            li.appendChild(link);
            sourcesList.appendChild(li);
        });
    }
    
    // Function to load database status
    function loadDatabaseStatus() {
        // Update the inline status card
        document.getElementById('db-status-loading').classList.remove('d-none');
        document.getElementById('db-status-content').classList.add('d-none');
        
        fetch('/api/status')
            .then(response => {
                if (!response.ok) {
                    throw new Error('Failed to load status: ' + response.statusText);
                }
                return response.json();
            })
            .then(data => {
                // Update the status card
                document.getElementById('db-collection-name').textContent = data.collection_name || '-';
                document.getElementById('db-document-count').textContent = data.document_count || '0';
                document.getElementById('db-embedding-model').textContent = data.embedding_model || '-';
                
                document.getElementById('db-status-loading').classList.add('d-none');
                document.getElementById('db-status-content').classList.remove('d-none');
            })
            .catch(error => {
                console.error('Error loading status:', error);
                document.getElementById('db-status-loading').classList.add('d-none');
                document.getElementById('db-status-content').classList.remove('d-none');
                document.getElementById('db-collection-name').textContent = 'Error loading status';
            });
    }
    
    // Function to show status modal with details
    function showStatusModal() {
        // Reset and show modal
        document.getElementById('modal-status-loading').classList.remove('d-none');
        document.getElementById('modal-status-content').classList.add('d-none');
        statusModal.show();
        
        // Fetch the latest status
        fetch('/api/status')
            .then(response => response.json())
            .then(data => {
                // Update modal content
                document.getElementById('modal-collection-name').textContent = data.collection_name || '-';
                document.getElementById('modal-document-count').textContent = data.document_count || '0';
                document.getElementById('modal-embedding-model').textContent = data.embedding_model || '-';
                document.getElementById('modal-embedding-dimension').textContent = data.embedding_dimension || '-';
                
                document.getElementById('modal-status-loading').classList.add('d-none');
                document.getElementById('modal-status-content').classList.remove('d-none');
            })
            .catch(error => {
                console.error('Error:', error);
                document.getElementById('modal-status-loading').classList.add('d-none');
                document.getElementById('modal-status-content').classList.remove('d-none');
                document.getElementById('modal-collection-name').textContent = 'Error loading status';
            });
    }
});