// Get DOM elements
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const resetBtn = document.getElementById('resetBtn');
const chatMessages = document.getElementById('chatMessages');
const themeToggle = document.getElementById('themeToggle');

// Dynamic Lightbox Elements (Resolves zoom overlay)
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightboxImg');

// Theme handling
const storedTheme = localStorage.getItem('clarilux-theme');
const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;

if (storedTheme === 'light' || (!storedTheme && prefersLight)) {
    document.body.classList.add('theme-light');
    themeToggle.textContent = '☀︎';
} else {
    themeToggle.textContent = '☾';
}

themeToggle.addEventListener('click', () => {
    const isLight = document.body.classList.toggle('theme-light');
    localStorage.setItem('clarilux-theme', isLight ? 'light' : 'dark');
    themeToggle.textContent = isLight ? '☀︎' : '☾';
});

// Event listeners
let autoScroll = true;

// Track user scroll: if the user scrolls away from the bottom, stop auto-scrolling
chatMessages.addEventListener('scroll', () => {
    const atBottom = (chatMessages.scrollHeight - chatMessages.scrollTop) <= (chatMessages.clientHeight + 8);
    autoScroll = atBottom;
});

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
resetBtn.addEventListener('click', resetChat);

// Send message function
async function sendMessage() {
    const message = userInput.value.trim();
    
    if (!message) {
        return;
    }
    
    // Add user message to chat
    addMessage(message, 'user');
    
    // Clear input
    userInput.value = '';
    
    // Disable buttons while processing
    sendBtn.disabled = true;
    resetBtn.disabled = true;
    
    // Show loading indicator
    const loadingDiv = addMessage('Thinking', 'bot-loading');
    
    try {
        let response;
        let retries = 3;
        let delay = 2000; // Start with a 2-second delay if rate limited

        // Keep attempting the request if we hit a rate limit (429)
        while (retries > 0) {
            response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message })
            });

            // If we hit a 429 Rate Limit error, pause and retry
            if (response.status === 429) {
                retries--;
                console.warn(`Rate limited by API. Retrying in ${delay / 1000}s... (${retries} retries left)`);
                await new Promise(resolve => setTimeout(resolve, delay));
                delay *= 1.5; // Exponential backoff
                continue;
            }

            break;
        }
        
        // Remove loading message
        loadingDiv.remove();
        
        if (response.ok) {
            const data = await response.json();
            // Pass BOTH the text response and the extracted images list to addMessage
            addMessage(data.response, 'bot', data.images);
        } else {
            const errorData = await response.json();
            if (response.status === 429) {
                addMessage("Groq is currently rate-limiting requests. Please wait a moment before trying again.", 'error');
            } else {
                addMessage(`Error: ${errorData.detail || 'Something went wrong.'}`, 'error');
            }
        }
    } catch (error) {
        if (loadingDiv) loadingDiv.remove();
        addMessage(`Error: ${error.message}`, 'error');
        console.error('Error:', error);
    } finally {
        // Re-enable buttons
        sendBtn.disabled = false;
        resetBtn.disabled = false;
        
        // Focus input
        userInput.focus();
    }
}

// Add message to chat function (Updated to parse Markdown for bot responses)
function addMessage(message, sender, imageUrls = []) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('message');
    
    if (sender === 'user') {
        messageDiv.classList.add('user-message');
    } else if (sender === 'bot') {
        messageDiv.classList.add('bot-message');
    } else if (sender === 'bot-loading') {
        messageDiv.classList.add('bot-message', 'loading');
    } else if (sender === 'error') {
        messageDiv.classList.add('bot-message', 'error-message');
    }
    
    // 1. Set up and append the textual content
    const messageContent = document.createElement('div'); // Swapped 'p' for 'div' to support complex block structures like lists/code block wrappers
    messageContent.classList.add('message-text');

    if (sender === 'bot-loading') {
        messageContent.innerHTML = `<p>${message}<span class="typing-dots"><span></span><span></span><span></span></span></p>`;
    } else if (sender === 'bot') {
        // Run bot responses through the Marked library parser (enabling breaks ensures single line returns work cleanly)
        messageContent.innerHTML = marked.parse(message, { breaks: true });
    } else {
        // Keep user and error text entirely flat and secure to prevent script execution vulnerabilities
        const plainTextPara = document.createElement('p');
        plainTextPara.textContent = message;
        messageContent.appendChild(plainTextPara);
    }
    messageDiv.appendChild(messageContent);
    
    // 2. Inject screenshots inside an orderly grid framework with stagger delays
    if (imageUrls && imageUrls.length > 0) {
        const imageGallery = document.createElement('div');
        imageGallery.classList.add('screenshot-gallery', 'image-gallery');
        
        imageUrls.forEach((url, index) => {
            const img = document.createElement('img');
            img.src = url; 
            img.alt = 'Clarilux Step Screenshot';
            img.classList.add('chat-screenshot', 'gallery-img');
            
            // Apply professional micro-interaction staggered delay
            img.style.animation = `messageSlideUp 0.25s cubic-bezier(0.05, 0.7, 0.1, 1) ${index * 0.08}s both`;
            
            // Trigger overlay active view state instead of breaking window tab navigation
            img.onclick = () => openLightbox(url);
            
            imageGallery.appendChild(img);
        });
        
        messageDiv.appendChild(imageGallery);
    }

    // 3. Attach thumbs up/down evaluation metrics bar to valid bot responses
    if (sender === 'bot') {
        const trackingId = `txn_${Math.random().toString(36).substring(2, 11)}`;
        const feedbackBar = document.createElement('div');
        feedbackBar.className = 'feedback-bar';
        feedbackBar.innerHTML = `
            <button class="feedback-action" onclick="submitTelemetry('${trackingId}', 'up', this)">👍</button>
            <button class="feedback-action" onclick="submitTelemetry('${trackingId}', 'down', this)">👎</button>
        `;
        messageDiv.appendChild(feedbackBar);
    }
    
    chatMessages.appendChild(messageDiv);

    // Scroll to bottom only when the user hasn't scrolled up
    if (autoScroll) {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    return messageDiv;
}

// Reset chat function
async function resetChat() {
    if (!confirm('Are you sure you want to reset the chat? This will clear the conversation history.')) {
        return;
    }
    
    try {
        const response = await fetch('/api/reset', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        if (response.ok) {
            chatMessages.innerHTML = '';
            
            const welcomeDiv = document.createElement('div');
            welcomeDiv.classList.add('message', 'bot-message');
            const welcomeContent = document.createElement('div');
            welcomeContent.classList.add('message-text');
            welcomeContent.innerHTML = "<p>Hello! I'm Clarilux Chatbox. How can I help you today?</p>";
            welcomeDiv.appendChild(welcomeContent);
            chatMessages.appendChild(welcomeDiv);
            
            userInput.value = '';
            userInput.focus();
        } else {
            alert('Failed to reset chat');
        }
    } catch (error) {
        alert(`Error resetting chat: ${error.message}`);
        console.error('Error:', error);
    }
}

/* Lightbox Modal Helper Functions */
function openLightbox(sourceUrl) {
    if (lightbox && lightboxImg) {
        lightboxImg.src = sourceUrl;
        // Dynamically name the alt text so it matches the specific asset being loaded
        lightboxImg.alt = "Clarilux Screenshot Preview - " + sourceUrl.split('/').pop();
        lightbox.classList.add('active');
    }
}

function closeLightbox() {
    if (lightbox) {
        lightbox.classList.remove('active');
    }
}

/* Telemetry Interaction Logging */
function submitTelemetry(msgId, ratingType, element) {
    const parent = element.parentElement;
    const buttons = parent.querySelectorAll('.feedback-action');
    
    // Clear out active toggle classes from alternative button paths
    buttons.forEach(btn => btn.className = 'feedback-action');

    // Target active styling hooks
    element.classList.add(ratingType === 'up' ? 'up-voted' : 'down-voted');
    
    console.log(`[Metrics Logging] Response ID: ${msgId} | Registered Action: ${ratingType.toUpperCase()}`);
}

// Set initial focus
userInput.focus();