import React, { useState } from 'react';
import SearchBar from './SearchBar';
import VideoDisplay from './VideoDisplay';

const App = () => {
    const [videoLinks, setVideoLinks] = useState([]);

    const handleSearch = (query) => {
        fetch('/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query }),
        })
            .then((res) => res.ok ? res.json() : Promise.reject('Search failed'))
            .then((data) => setVideoLinks(data.links || []))
            .catch((err) => console.error('Search error:', err));
    };

    return (
        <div className="app">
            <SearchBar onSearch={handleSearch} />
            <VideoDisplay urls={videoLinks} />
        </div>
    );
};

export default App;
