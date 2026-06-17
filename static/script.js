// Get DOM elements
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const resetBtn = document.getElementById('resetBtn');
const chatMessages = document.getElementById('chatMessages');

// Event listeners
sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
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
    const loadingDiv = addMessage('Thinking...', 'bot-loading');
    
    try {
        // Send message to backend
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message })
        });
        
        // Remove loading message
        loadingDiv.remove();
        
        if (response.ok) {
            const data = await response.json();
            addMessage(data.response, 'bot');
        } else {
            const errorData = await response.json();
            addMessage(`Error: ${errorData.detail}`, 'error');
        }
    } catch (error) {
        loadingDiv.remove();
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

// Add message to chat function
function addMessage(message, sender) {
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
    
    const messageContent = document.createElement('p');
    messageContent.textContent = message;
    messageDiv.appendChild(messageContent);
    
    chatMessages.appendChild(messageDiv);
    
    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
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
            // Clear messages
            chatMessages.innerHTML = '';
            
            // Add welcome message
            const welcomeDiv = document.createElement('div');
            welcomeDiv.classList.add('message', 'bot-message');
            const welcomeContent = document.createElement('p');
            welcomeContent.textContent = "Hello! I'm Gemini Chatbot. How can I help you today?";
            welcomeDiv.appendChild(welcomeContent);
            chatMessages.appendChild(welcomeDiv);
            
            // Clear input
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

// Set initial focus
userInput.focus();
